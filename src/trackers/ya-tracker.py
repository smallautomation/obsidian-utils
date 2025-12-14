"""
:author     komarov.i@tn.ru
:doc_link   https://tracker.yandex.ru/EDWH-177
:date       2025-09-18
:version    2.0.0
"""

from datetime import datetime, date, timedelta
import json
import pathlib
import re
import logging
import toml
import os
import subprocess
import warnings
from time import sleep
import gitlab
from pathlib import Path

import click
import pandas as pd
import requests
from gitlab import GitlabError
from pytimeparse import parse
from simple_term_menu import TerminalMenu


# отключение многочисленных предупреждений pandas
warnings.filterwarnings('ignore')

# путь к справочнику пользователей
settings = toml.load(f'{pathlib.Path(__file__).parent.resolve()}/config.toml')
gitlab_user_token = settings['gitlab_user_token']
gitlab_group_id = settings['gitlab_group_id']
tracker_project_id = settings['tracker_project_id']
tracker_issue_statuses = settings['tracker_issue_statuses']
daily_work_reports = settings['daily_work_reports']
obsidian_vault_path = settings['obsidian_vault_path']


# Настраиваем логирование
def setup_logging(level=logging.INFO, log_file='ya_tracker.log'):
    """Настройка логирования с выводом в файл и консоль"""

    # Убедимся, что директория для логов существует
    log_path = Path(log_file)
    if log_path.parent and not log_path.parent.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Создаем логгер
    logger = logging.getLogger('obsidian_parser')
    logger.setLevel(level)

    # Очищаем существующие обработчики
    logger.handlers.clear()

    # Форматтер для логов
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        # Обработчик для файла
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

        # Проверяем, что файл создан
        if os.path.exists(log_file):
            logger.info(f"Лог-файл создан: {os.path.abspath(log_file)}")
        else:
            logger.error(f"Не удалось создать лог-файл: {log_file}")

    except Exception as e:
        print(f"Ошибка при создании файла логов: {e}")
        # Создаем только консольный обработчик если файл не создался

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    return logger

# Функция для логирования сообщений
def log_message(message, level='info', logger=None):
    """
    Логирование сообщений с разными уровнями

    Args:
        message: Сообщение для логирования
        level: Уровень логирования ('debug', 'info', 'warning', 'error', 'critical')
        logger: Экземпляр логгера (если None, используется корневой логгер)
    """
    if logger is None:
        logger = logging.getLogger('obsidian_parser')

    level_map = {
        'debug': logger.debug,
        'info': logger.info,
        'warning': logger.warning,
        'error': logger.error,
        'critical': logger.critical
    }

    log_func = level_map.get(level.lower(), logger.info)
    log_func(message)


setup_logging()

gl = gitlab.Gitlab(url='https://gitlab.tn.ru', private_token=gitlab_user_token)
gl.auth()

user = gl.users.get(gl.user.id)
# Получаем проект по ID или имени
group = gl.groups.get(gitlab_group_id)

# Получаем список участников проекта
# members = group.members.list(all=True)

projects = gl.projects.list(owned=True, all=True)


def get_user_projects(user_id):
    """Получаем все проекты, где участвует пользователь"""
    try:
        user = gl.users.get(user_id)
        return user.projects.list(all=True)
    except Exception as e:
        print(f"Ошибка при получении проектов пользователя: {e}")
        return []


def parse_datetime_with_tz(date_str):
    # Удаляем миллисекунды и парсим дату
    date_str = date_str.rsplit('.', 1)[0]
    naive_datetime = datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S')
    return naive_datetime.astimezone(datetime.timezone.utc)

def is_branch_recent(branch, days=30):
    """Проверяет, был ли последний коммит в ветке не старше указанного количества дней"""
    try:
        last_commit_info = branch.commit

        if isinstance(last_commit_info, dict):
            commit_date_str = last_commit_info.get('committed_date')
        else:
            commit_date_str = getattr(last_commit_info, 'committed_date', None)

        if commit_date_str:
            last_commit_date = parse_datetime_with_tz(commit_date_str)
            return (datetime.datetime.now(datetime.timezone.utc) - last_commit_date) <= datetime.timedelta(days=days)

        return False
    except Exception as e:
        print(f"Ошибка при проверке даты коммита ветки {branch.name}: {e}")
        return False

def get_commits_for_date(project, date):
    """
    Получаем коммиты в проекте за указанную дату
    :param project: объект проекта GitLab
    :param date: строка с датой в формате YYYY-MM-DD
    :return: список коммитов
    """
    try:
        # Валидируем входную дату
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")

        # Устанавливаем корректные временные границы
        start_date = date_obj.strftime("%Y-%m-%dT00:00:00Z")
        end_date = (date_obj + datetime.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

        # Получаем все ветки проекта
        branches = project.branches.list(all=True)

        all_commits = []
        for branch in branches:
            if is_branch_recent(branch):
                try:
                    # Получаем коммиты для каждой ветки
                    commits = project.commits.list(
                        ref_name=branch.name,
                        since=start_date,
                        until=end_date,
                        all=True
                    )
                    all_commits.extend(commits)
                except Exception as e:
                    print(f"Ошибка при получении коммитов ветки {branch.name}: {e}")

        return all_commits

    except ValueError as ve:
        print(f"Ошибка формата даты для проекта {project.name}: {ve}")
        return []

    except GitlabError as ge:
        print(f"Ошибка GitLab API для проекта {project.name}: {ge}")
        return []

    except Exception as e:
        print(f"Непредвиденная ошибка для проекта {project.name}: {e}")
        return []


def filter_commits_by_author(commits, author_email):
    """Фильтруем коммиты по автору"""
    return list(set([commit.title for commit in commits if commit.author_email == author_email and commit.title.startswith('EDWH-')]))

default_date = str(date.today())

# for project in projects:
#     commits = get_commits_for_date(project, default_date)
#     print(filter_commits_by_author(commits, gl.user.commit_email))

def get_iam_token():
    return subprocess.run(["/home/aborisov/yandex-cloud/bin/yc", "iam", "create-token"], stdout=subprocess.PIPE, text=True).stdout.rstrip()

def print_issues(issues):
    """
    Форматируем и выводим информацию о задачах
    """
    for issue in issues:
        print(f"Задача: {issue.get('summary')}")
        print(f"ID: {issue.get('id')}")
        print(f"Статус: {issue.get('status', {}).get('display')}")
        print(f"Ключ: {issue.get('key')}")
        print("-" * 40)

@click.command()
@click.option('--token', '-t', default=get_iam_token(),
              help="Можно указать IAM токен вручную, но штатно он будет получен через Яндекс.Консоль",
              type=str, show_default=True, )
@click.option('--create_date_from', '-from',
              default= date.today() + timedelta(days=-date.today().weekday(), weeks=-1),
              help="Дата начала загрузки трудоотчетов, по умолчанию "
                   "понедельник прошлой недели",
              type=str, show_default=True)
@click.option('--create_date_to', '-to',
              default=date.today() + timedelta(days=-date.today().weekday() + 6),
              help="Дата окончания загрузки трудоотчетов, по умолчанию "
                   "воскресенье текущей недели",
              type=str, show_default=True)
@click.option('--org_id', '-id', default=5865658, help="ID организации из панели Яндекс.Трекера",
              type=int, show_default=True)
@click.option('--project_id', '-p', default=tracker_project_id,
              help="Числовой код проекта в Yandex.Tracker",
              type=str, show_default=True, )
def main(token: str, create_date_from: str, create_date_to: str, org_id: int, project_id: str):
    """
    Утилита для работы с трудоотчетами в Yandex Tracker \n
    Sleep необходим, чтобы трекер успел отдать обновленные данные

    Args:  \n
        token:                          IAM токен для доступа к API
        create_date_from:               Дата начала загрузки трудоотчетов, по умолчанию понедельник прошлой недели \n
        create_date_to:                 Дата окончания загрузки трудоотчетов, по умолчанию воскресенье текущей недели \n
        org_id:                         ID организации в Яндекс.Трекере
        project_id:                     ID проекта в Яндекс.Трекере
    """

    def create_options(options_list: list[str], title: str) -> tuple[int | None, list[str]]:
        """
        Функция для создания опций меню

        Args:
            options_list:
            title:

        Returns:

        """
        options = [f'[{index + 1}] {option}' for index, option in enumerate(options_list)]
        options.append(f'[{len(options) + 1}] Выйти')
        terminal_menu = TerminalMenu(options, title=title)
        menu_entry_index = terminal_menu.show()
        return menu_entry_index, options
    # click.secho(create_date_from, fg='bright_red')
    # click.secho(create_date_to, fg='bright_red')

    current_user = gl.user.commit_email
    show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
    # Главное меню программы
    main_options = [
        "[1] Показать трудоотчеты по дате",
        "[2] Показать трудоотчеты по задаче",
        "[3] Создать трудоотчёт",
        "[4] Обновить отчет",
        "[5] Выбрать сотрудника из справочника",
        "[6] Настройки",
        "[7] Выйти",
    ]
    main_terminal_menu = TerminalMenu(main_options, title="Главное меню")
    while True:
        menu_entry_index = main_terminal_menu.show()
        click.echo(main_options[menu_entry_index])
        if menu_entry_index == 6:
            exit(0)
        if menu_entry_index == 3:
            show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
        elif menu_entry_index == 2:
            target_date = valid_date_input()

            click.secho(
                f'Возможно, придется, немного опдождать из-за большого количества веток. После чистки процесс ускорится.',
                fg='bright_blue')
            probable_workreports = []
            for project in projects:
                commits = get_commits_for_date(project, target_date)
                probable_workreports.extend(filter_commits_by_author(commits, current_user))

            # separator = "\n\n"
            # probable_workreports.extend([commit.split(separator)[0] for commit in probable_workreports if commit.split(separator)[0].startswith('EDWH-')])
            issues = get_user_issues(current_user, org_id, token)
            for issue in issues:
                probable_workreports.append(f"{issue.get('key')} {issue.get('summary')}")
            probable_workreports.extend(daily_work_reports)
            probable_workreports.insert(0, 'Ввести свой вариант')
            workreports_index, workreports_options = create_options(probable_workreports, f'Варианты заполнения трудозатрат')
            if 'Выйти' in workreports_options[workreports_index]:
                exit(0)

            def remove_bracketed_text(text):
                # Регулярное выражение для поиска текста в квадратных скобках
                pattern = r'\[.*?\]'
                # Удаляем все совпадения
                cleaned_text = re.sub(pattern, '', text)
                trimmed_text = re.sub(r'^\s+|\s+$', '', cleaned_text)
                return trimmed_text

            if 'Ввести свой вариант' in workreports_options[workreports_index]:
                result = []
            else:
                result = re.split(r'\s', remove_bracketed_text(workreports_options[workreports_index]), maxsplit=1)
            if len(result) == 0:
                click.secho(
                    f'Подсказки по номерам задач:\n 180 - Оргвопросы,\n 181 - Отпуска, отсутствия, болезни,\n'
                    f' 182 - Повышение квалификации,\n 1610 - Мелкие работы по сопровождению EDWH',
                    fg='bright_blue')
                task_number = task_number_input(project_id)
                click.secho(
                    f'Комментарий к задаче обязателен! Название указанной задачи - {get_task_name_by_key(token, org_id, task_number)}',
                    fg='bright_blue')
                comment = ''
                while len(comment)==0:
                    comment = click.prompt("Введите новый комментарий к трудозатратам", default=remove_bracketed_text(get_task_name_by_key(token, org_id, task_number)))
            else:
                task_number = int(result[0].replace("EDWH-", ''))
                comment = result[-1]
            click.secho(
                f'Возможен ввод значений до 8h (техническое ограничение)',
                fg='bright_blue')
            duration = duration_input()
            add_worklog_to_task(task_number, target_date, duration, comment, org_id, token, project_id)
            sleep(1)
            show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
        elif menu_entry_index == 4:
            usernames = []
            for member in members:
                usernames.append(f'{member.username}@tn.ru') if member.username != 'root' else None
            usernames_terminal_menu = TerminalMenu(usernames, title="Выберите пользователя:")
            username_menu_entry_index = usernames_terminal_menu.show()
            current_user = usernames[username_menu_entry_index]
            show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
        elif menu_entry_index == 1:
            task_number = task_number_input(project_id)
            show_works_by_task(task_number, org_id, token, project_id)
            manage_works(create_date_from, create_date_to, current_user, org_id, project_id, token,
                         show_works_by_task, task_number, project_id)
        elif menu_entry_index == 0:
            valid_date = valid_date_input()
            show_worklogs_by_date(current_user, org_id, token, valid_date)
            manage_works(create_date_from, create_date_to, current_user, org_id, project_id, token,
                         show_worklogs_by_date, current_user, valid_date)
        elif menu_entry_index == 5:
            settings_works_options = [
                "[1] Изменить имя пользователя",
                "[2] Изменить проект",
                "[3] Изменить интервал отображаемых дат",
                "[4] Вернуться к предыдущему меню",
                "[5] Выйти",
            ]
            settings_terminal_menu = TerminalMenu(settings_works_options, title="Управление настройками")
            while True:
                settings_menu_entry_index = settings_terminal_menu.show()
                click.echo(settings_works_options[settings_menu_entry_index])
                if settings_menu_entry_index == 0:
                    text = click.prompt(
                        'Введите логин для поиска информации (e-mail до @, @tn.ru будет добавлено автоматически)')
                    current_user = f"{text}@tn.ru"
                    show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
                elif settings_menu_entry_index == 4:
                    exit(0)
                elif settings_menu_entry_index == 3:
                    show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
                    break
                elif settings_menu_entry_index == 1:
                    project_id = f"{click.prompt('Введите код проекта в трекере')}"
                    show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
                    break
                elif settings_menu_entry_index == 2:
                    click.secho(
                        f'Введите дату начала интервала отображения (утилита не рассчитана на интервалы > 2 недель)',
                        fg='bright_green')
                    create_date_from = valid_date_input()
                    click.secho(f'Введите дату окончания интервала отображения', fg='bright_green')
                    create_date_to = valid_date_input()
                    dt_f = '%Y-%M-%d'
                    if datetime.datetime.strptime(create_date_from, dt_f) > datetime.datetime.strptime(create_date_to,
                                                                                                       dt_f):
                        click.secho(f'Дата начала интервала {create_date_from} больше даты окончания {create_date_to}. '
                                    f'Введите другие даты.',
                                    fg='bright_red')
                    show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
                    break

def manage_works(create_date_from: str, create_date_to: str, current_user: str, org_id: int, project: str, token: str,
                 refresh_data_function: callable, function_param1: any, function_param2: any):
    """
    Показывает меню, позволяющее управлять трудоотчетами и обрабатывает действия в нем
    Args:
        create_date_from (str):             дата начала интервала для получения данных
        create_date_to (str):               дата окончания интервала для получения данных
        current_user (str):                 активный пользователь для получения данных
        org_id (int):                       идентификатор организации из трекера
        project (str):                      идентификатор проекта из трекера
        token (str):                        IAM токен
        refresh_data_function (callable):   функция, запускаемая для обновления данных
        function_param1 (any):              параметр функции для запуска
        function_param2 (any):              параметр функции для запуска
    """
    manage_works_options = [
        "[1] Редактировать трудоотчет и комментарий",
        "[2] Редактировать трудоотчет",
        "[3] Удалить трудоотчет",
        "[4] Вернуться к предыдущему меню",
        "[5] Выйти",
    ]
    manage_works_terminal_menu = TerminalMenu(manage_works_options, title="Управление трудозатратами")
    while True:
        manage_works_menu_entry_index = manage_works_terminal_menu.show()
        click.echo(manage_works_options[manage_works_menu_entry_index])
        if manage_works_menu_entry_index == 4:
            exit(0)
        elif manage_works_menu_entry_index == 3:
            show_works_by_date_and_user(create_date_from, create_date_to, current_user, org_id, token)
            break
        elif manage_works_menu_entry_index == 2:
            task_number = task_number_input(project)
            worklog_number = worklog_number_input()
            delete_worklogs_by_number(task_number, worklog_number, org_id, token, project)
            sleep(0.5)
            refresh_data_function(function_param1, org_id, token, function_param2)
        elif manage_works_menu_entry_index == 0:
            task_number = task_number_input(project)
            worklog_number = worklog_number_input()
            new_duration = duration_input()
            new_comment = click.prompt("Введите новый комментарий к трудозатратам")
            change_worklogs_by_number(task_number, worklog_number, new_duration, org_id, token,
                                      project, new_comment=new_comment)
            sleep(0.5)
            refresh_data_function(function_param1, org_id, token, function_param2)
        elif manage_works_menu_entry_index == 1:
            task_number = task_number_input(project)
            worklog_number = worklog_number_input()
            new_duration = duration_input()
            change_worklogs_by_number(task_number, worklog_number, new_duration, org_id, token, project)
            sleep(0.5)
            refresh_data_function(function_param1, org_id, token, function_param2)


def show_worklogs_by_date(current_user: str, org_id: int, token: str, valid_date: str):
    """
    Обработка и отображение трудоотчетов по пользователю за конкретную дату
    Args:
        valid_date (datetime):           дата для получения трудоотчетов
        current_user (str):         активный пользователь для получения данных
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
    """
    answer = request_worklogs_by_date(valid_date, valid_date, current_user, org_id, token)
    df = (pd.json_normalize(answer))
    if df.empty:
        click.secho(f'Информация по сотруднику {current_user} за {valid_date} не обнаружена.',
                    fg='bright_red')
        return
    if "comment" not in df.columns:
        df.insert(1, "comment", 'NaN')
    df1 = df[["issue.key", "issue.display", "id", "comment", "start", "duration", ]]
    df1["start"] = pd.to_datetime(df1["start"], utc=True).dt.tz_convert('Europe/Moscow').dt.to_period("D")
    df1["duration"] = df1["duration"].str.replace('P', '', regex=True, ).replace('T', '', regex=True, ).apply(
        parse).map(lambda x: x / 3600)
    # df1.sort_values('issue.key', ascending=False)
    df1.rename(columns={'issue.key': 'Номер задачи',
                        'issue.display': 'Название задачи',
                        'id': 'Номер отчёта',
                        'comment': 'Комментарий',
                        'start': 'Дата списания',
                        'duration': 'Длительность',
                        }, inplace=True)
    click.secho(f'Информация по сотруднику {current_user} за {valid_date}', fg='bright_green')
    click.secho(f'Если указанное число превышает 24 часа, то это значит одно из списаний времени превышает 8h. Это нормально, сложно настроить правильное отображение. 25 = 9h', fg='bright_blue')
    df1.loc['Сумма часов'] = pd.Series(df1['Длительность'].sum(), index=['Длительность'])
    click.secho(df1, fg='bright_yellow')


def _format_pivot_with_discrepancies(df1):
    """
    Создает сводную таблицу с маркерами расхождений, правильным выравниванием и обрезкой текста
    """
    import click

    # Собираем уникальные даты в правильном порядке
    dates = sorted(df1['Дата списания'].unique())

    # Определяем ширину колонок
    TASK_KEY_WIDTH = 12
    TASK_NAME_WIDTH = 50
    TASK_LINK_WIDTH = 40
    # Ширина для значения (включая пробел справа)
    VALUE_WIDTH = 12

    # Вычисляем общую ширину
    total_width = TASK_KEY_WIDTH + TASK_NAME_WIDTH + TASK_LINK_WIDTH + len(dates) * VALUE_WIDTH + 2

    # Создаем заголовок
    result_lines = []

    # Заголовок 1: "Длительность" по центру
    values_width = len(dates) * VALUE_WIDTH
    header1 = f"{'Номер задачи':<{TASK_KEY_WIDTH}} {'Название задачи':<{TASK_NAME_WIDTH}} {'Ссылка на задачу':<{TASK_LINK_WIDTH}}"
    header1 += "Длительность".center(values_width)
    result_lines.append(header1)

    # Заголовок 2: Даты
    header2 = " " * (TASK_KEY_WIDTH + TASK_NAME_WIDTH + TASK_LINK_WIDTH + 2)
    for date in dates:
        date_str = str(date)[:10]
        header2 += f"{date_str:^{VALUE_WIDTH}}"
    result_lines.append(header2)

    # Заголовок 3: Дни недели - ВЫРАВНИВАЕМ ВПРАВО
    header3 = " " * (TASK_KEY_WIDTH + TASK_NAME_WIDTH + TASK_LINK_WIDTH + 2)
    for date in dates:
        weekday = df1[df1['Дата списания'] == date]['День недели'].iloc[0]
        # ВЫРАВНИВАЕМ ВПРАВО вместо центрирования
        header3 += f"{weekday:>{VALUE_WIDTH}}"
    result_lines.append(header3)

    # Разделитель
    result_lines.append("=" * total_width)

    # Группируем по задачам
    grouped = df1.groupby(['Номер задачи', 'Название задачи', 'Ссылка на задачу'])

    for (task_key, task_name, task_link), group in grouped:
        # Обрезаем текст
        display_name = (task_name[:TASK_NAME_WIDTH - 3] + "...") if len(task_name) > TASK_NAME_WIDTH else task_name
        display_link = (task_link[:TASK_LINK_WIDTH]) if len(task_link) > TASK_LINK_WIDTH else task_link

        # Начинаем строку
        line = f"{task_key:<{TASK_KEY_WIDTH}} {display_name:<{TASK_NAME_WIDTH}} {display_link:<{TASK_LINK_WIDTH}}"

        # Собираем части строки для форматирования с цветом
        line_parts = [line]

        # Добавляем значения для каждой даты
        for date in dates:
            date_group = group[group['Дата списания'] == date]

            if not date_group.empty:
                duration = float(date_group['Длительность'].sum())

                # Проверяем расхождения
                has_discrepancy = False
                if 'Статус (obsidian)' in date_group.columns and 'Совпадение' in date_group.columns:
                    mask = (
                            (date_group['Статус (obsidian)'] == 'completed') &
                            (date_group['Совпадение'] == False)
                    )
                    has_discrepancy = mask.any()

                # Форматируем значение с учетом выравнивания
                formatted_value = f"{duration:>{VALUE_WIDTH - 1}.1f} "

                if has_discrepancy:
                    # Выделяем всю длительность красным цветом
                    colored_value = click.style(formatted_value, fg='red')
                    line_parts.append(colored_value)
                else:
                    line_parts.append(formatted_value)
            else:
                line_parts.append(f"{0.0:>{VALUE_WIDTH - 1}.1f} ")

        # Собираем строку
        colored_line = ''.join(line_parts)
        result_lines.append(colored_line)

    # Разделитель
    result_lines.append("-" * total_width)

    # Итоговая строка
    total_line = f"{'All':<{TASK_KEY_WIDTH}} {'':<{TASK_NAME_WIDTH}} {'':<{TASK_LINK_WIDTH}}"

    for date in dates:
        date_total = float(df1[df1['Дата списания'] == date]['Длительность'].sum())
        total_line += f"{date_total:>{VALUE_WIDTH - 1}.1f} "

    result_lines.append(total_line)

    return result_lines


def _print_discrepancies_summary(obsidian_only_tasks, tracker_discrepancies):
    """Выводит детальную расшифровку всех расхождений после таблицы"""

    total_issues = len(obsidian_only_tasks) + len(tracker_discrepancies)

    if total_issues == 0:
        click.secho('\n✓ Все данные синхронизированы, расхождений не обнаружено.', fg='bright_green')
        return

    click.secho(f'\n{"=" * 80}', fg='bright_yellow')
    click.secho('РАСШИФРОВКА РАСХОЖДЕНИЙ', fg='bright_yellow', bold=True)
    click.secho(f'Всего найдено расхождений: {total_issues}', fg='bright_yellow')
    click.secho(f'{"=" * 80}', fg='bright_yellow')

    # 1. Задачи, которые есть только в Obsidian
    if obsidian_only_tasks:
        click.secho('\n📝 ЗАДАЧИ, КОТОРЫЕ ЕСТЬ ТОЛЬКО В OBSIDIAN:', fg='bright_cyan')
        click.secho('(Эти задачи отсутствуют в трекере и требуют создания)', fg='bright_cyan')

        # Группируем по датам
        by_date = {}
        for task in obsidian_only_tasks:
            date = task['date']
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(task)

        # Сортируем по дате
        for date in sorted(by_date.keys()):
            tasks = by_date[date]
            total_hours = sum(t['obsidian_duration'] for t in tasks)

            click.secho(f'\n  📅 Дата {date} ({len(tasks)} задач, всего {total_hours:.1f} ч):', fg='white')

            for task in tasks:
                status_color = 'green' if task['obsidian_status'] == 'completed' else 'yellow'
                click.secho(f'    • {task["task_key"]}: {task["obsidian_duration"]} ч '
                            f'({task["obsidian_info"]})',
                            fg=status_color)

    # 2. Расхождения в длительности
    if tracker_discrepancies:
        click.secho('\n⚠️  РАСХОЖДЕНИЯ В ДЛИТЕЛЬНОСТИ:', fg='bright_red')
        click.secho('(Часы в трекере и Obsidian не совпадают)', fg='bright_red')

        # Группируем по датам
        by_date = {}
        for disc in tracker_discrepancies:
            date = disc['date']
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(disc)

        # Сортируем по дате
        for date in sorted(by_date.keys()):
            discrepancies = by_date[date]
            total_diff = sum(d['difference'] for d in discrepancies)

            click.secho(f'\n  📅 Дата {date} ({len(discrepancies)} расхождений, общая разница: {total_diff:.1f} ч):',
                        fg='white')

            for disc in discrepancies:
                tracker_hours = disc['tracker_duration']
                obsidian_hours = disc['obsidian_duration']
                diff = disc['difference']

                # Определяем, где больше часов
                if obsidian_hours > tracker_hours:
                    direction = f"→ Obsidian больше на {diff:.1f} ч"
                    color = 'bright_red'
                else:
                    direction = f"→ Tracker больше на {diff:.1f} ч"
                    color = 'bright_yellow'

                click.secho(f'    • {disc["task_key"]}: ', nl=False)
                click.secho(f'Tracker={tracker_hours:.1f}ч, ', fg='cyan', nl=False)
                click.secho(f'Obsidian={obsidian_hours:.1f}ч ', fg='magenta', nl=False)
                click.secho(f'({direction})', fg=color)

    # 3. Сводная статистика
    click.secho(f'\n{"=" * 80}', fg='bright_yellow')
    click.secho('СВОДНАЯ СТАТИСТИКА:', fg='bright_yellow')

    if obsidian_only_tasks:
        obsidian_total = sum(t['obsidian_duration'] for t in obsidian_only_tasks)
        click.secho(f'• Задач только в Obsidian: {len(obsidian_only_tasks)} '
                    f'(всего {obsidian_total:.1f} ч)', fg='bright_cyan')

    if tracker_discrepancies:
        tracker_total = sum(d['tracker_duration'] for d in tracker_discrepancies)
        obsidian_total = sum(d['obsidian_duration'] for d in tracker_discrepancies)
        diff_total = sum(d['difference'] for d in tracker_discrepancies)

        click.secho(f'• Расхождений в длительности: {len(tracker_discrepancies)}', fg='bright_red')
        click.secho(f'• Сумма часов в трекере: {tracker_total:.1f} ч', fg='cyan')
        click.secho(f'• Сумма часов в Obsidian: {obsidian_total:.1f} ч', fg='magenta')
        click.secho(f'• Общая разница: {diff_total:.1f} ч', fg='bright_red')

    click.secho(f'{"=" * 80}', fg='bright_yellow')
    click.secho('\n💡 СОВЕТЫ:', fg='bright_green')

    if obsidian_only_tasks:
        click.secho('• Для задач только в Obsidian: необходимо создать соответствующие записи в трекере',
                    fg='white')

    if tracker_discrepancies:
        click.secho('• Для расхождений в длительности: сравните данные и обновите либо трекер, либо Obsidian',
                    fg='white')

    click.secho('• Используйте функцию синхронизации для автоматического выравнивания данных',
                fg='white')

def iso8601_to_hours(iso_str):
    if not iso_str or not isinstance(iso_str, str):
        return 0.0

    # Приводим к верхнему регистру для единообразия
    iso_str = iso_str.upper().strip()

    # Проверяем, что строка начинается с PT
    if not iso_str.startswith('PT'):
        # Пробуем интерпретировать как число
        try:
            return float(iso_str)
        except ValueError:
            return 0.0

    # Удаляем префикс PT
    duration_str = iso_str[2:]

    # Используем регулярное выражение для извлечения компонентов
    # Обрабатываем часы (H), минуты (M) и секунды (S)
    pattern = r'(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?'
    match = re.fullmatch(pattern, duration_str)

    if not match:
        return 0.0

    # Извлекаем компоненты
    hours = float(match.group(1)) if match.group(1) else 0.0
    minutes = float(match.group(2)) if match.group(2) else 0.0
    seconds = float(match.group(3)) if match.group(3) else 0.0

    # Конвертируем всё в часы
    total_hours = hours + (minutes / 60.0) + (seconds / 3600.0)

    return total_hours


def show_works_by_date_and_user(create_date_from: str, create_date_to: str, current_user: str, org_id: int, token: str):
    """
    Обработка и отображение трудоотчетов по пользователю за интервал времени
    Args:
        create_date_from (str):     дата начала интервала для получения данных
        create_date_to (str):       дата окончания интервала для получения данных
        current_user (str):         активный пользователь для получения данных
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
    """

    answer = request_worklogs_by_date(create_date_from, create_date_to, current_user, org_id, token)
    df = (pd.json_normalize(answer))

    # Парсим задачи из Obsidian
    obsidian_tasks = parse_obsidian_tasks(create_date_from, create_date_to, obsidian_vault_path=obsidian_vault_path)

    # Создаем списки для хранения разных типов расхождений
    obsidian_only_tasks = []  # Есть только в Obsidian
    tracker_discrepancies = []  # Расхождения в длительности (разные часы)

    if df.empty:
        # Если в трекере вообще нет задач, все задачи из Obsidian считаются расхождениями
        for date in obsidian_tasks:
            for task_key in obsidian_tasks[date]:
                task = obsidian_tasks[date][task_key]
                obsidian_only_tasks.append({
                    'date': date,
                    'task_key': task_key,
                    'tracker_duration': 0.0,
                    'obsidian_duration': task['duration_hours'],
                    'obsidian_status': task['status'],
                    'obsidian_info': f"{'✅' if task['status'] == 'completed' else '⏳'} {task['status']}",
                    'type': 'only_in_obsidian'
                })

        click.secho(f'Информация по сотруднику {current_user} c {create_date_from} до {create_date_to} не обнаружена.',
                    fg='bright_red')

        # Выводим расхождения
        if obsidian_only_tasks:
            _print_discrepancies_summary(obsidian_only_tasks, [])
        return

    # Добавляем отсутствующие колонки в DataFrame
    if "comment" not in df.columns:
        df.insert(1, "comment", 'NaN')
    if "obsidian_duration" not in df.columns:
        df.insert(3, "obsidian_duration", 0.0)
    if "obsidian_info" not in df.columns:
        df.insert(3, "obsidian_info", "❌ Нет в Obsidian")
    if "obsidian_status" not in df.columns:
        df.insert(3, "obsidian_status", "not_found")
    if "duration_match" not in df.columns:
        df.insert(3, "duration_match", True)

    # Множество для отслеживания найденных задач в Obsidian
    found_in_obsidian = set()

    # Заполняем данные из Obsidian для задач из трекера
    for idx, row in df.iterrows():
        task_key = row["issue.key"]
        start_date = pd.to_datetime(row["start"], utc=True).tz_convert('Europe/Moscow').strftime("%Y-%m-%d")

        # Ищем задачу в Obsidian по ключу и дате
        obsidian_found = False

        # Проверяем есть ли задачи на эту дату в Obsidian
        if start_date in obsidian_tasks:
            # Ищем конкретную задачу по ключу на эту дату
            if task_key in obsidian_tasks[start_date]:
                obsidian_task = obsidian_tasks[start_date][task_key]
                # Формируем строку статуса
                status_icon = "✅" if obsidian_task['status'] == 'completed' else "⏳"
                df.at[idx, "obsidian_duration"] = obsidian_task['duration_hours']
                df.at[idx, "obsidian_info"] = f"{status_icon} {obsidian_task['status']}"
                df.at[idx, "obsidian_status"] = obsidian_task['status']
                obsidian_found = True

                # Добавляем в множество найденных задач
                found_in_obsidian.add((start_date, task_key))

        # Если задача не найдена в Obsidian на нужную дату
        if not obsidian_found:
            df.at[idx, "obsidian_duration"] = 0
            df.at[idx, "obsidian_info"] = "❌ Нет в Obsidian"
            df.at[idx, "obsidian_status"] = "not_found"

    # Находим задачи, которые есть в Obsidian, но нет в трекере
    for date in obsidian_tasks:
        for task_key in obsidian_tasks[date]:
            if (date, task_key) not in found_in_obsidian:
                task = obsidian_tasks[date][task_key]
                obsidian_only_tasks.append({
                    'date': date,
                    'task_key': task_key,
                    'tracker_duration': 0.0,
                    'obsidian_duration': task['duration_hours'],
                    'obsidian_status': task['status'],
                    'obsidian_info': f"{'✅' if task['status'] == 'completed' else '⏳'} {task['status']}",
                    'type': 'only_in_obsidian'
                })

    # Проверяем совпадение длительностей для задач из трекера
    for idx, row in df.iterrows():
        tracker_duration = iso8601_to_hours(row["duration"])
        obsidian_duration = row["obsidian_duration"]
        duration_diff = abs(tracker_duration - obsidian_duration)

        # Используем точность сравнения 0.1 часа (6 минут)
        is_match = duration_diff < 0.1
        df.at[idx, "duration_match"] = is_match

        # Если есть расхождение и задача найдена в Obsidian
        if not is_match and row["obsidian_status"] != "not_found":
            start_date = pd.to_datetime(row["start"], utc=True).tz_convert('Europe/Moscow').strftime("%Y-%m-%d")

            tracker_discrepancies.append({
                'date': start_date,
                'task_key': row["issue.key"],
                'tracker_duration': tracker_duration,
                'obsidian_duration': obsidian_duration,
                'difference': duration_diff,
                'type': 'duration_mismatch'
            })

    # Подготовка данных для отображения
    df1 = df[["issue.key", "issue.display", "issue.self", "comment", "start", "duration",
              "obsidian_duration", "obsidian_status", "obsidian_info", "duration_match"]]

    df1["start"] = pd.to_datetime(df1["start"], utc=True).dt.tz_convert('Europe/Moscow')
    df1["date_only"] = df1["start"].dt.date
    df1["start"] = df1["start"].dt.to_period("D")

    day_of_week = {
        0: 'Понедельник',
        1: 'Вторник',
        2: 'Среда',
        3: 'Четверг',
        4: 'Пятница',
        5: 'Суббота',
        6: 'Воскресенье'
    }
    df1['weekday'] = df1['start'].dt.dayofweek.map(day_of_week)

    # Преобразование длительности из ISO8601 в часы
    df1["duration"] = df1["duration"].str.replace('P', '', regex=True).replace('T', '', regex=True).apply(parse).map(
        lambda x: x / 3600)

    # Формирование ссылки на задачу
    df1["issue.self"] = df1["issue.self"].str.replace('api.tracker.yandex.net', 'tracker.yandex.ru',
                                                      regex=True).replace('/v2/issues', '', regex=True)

    # Переименование колонок
    df1.rename(columns={
        'issue.key': 'Номер задачи',
        'issue.display': 'Название задачи',
        'issue.self': 'Ссылка на задачу',
        'comment': 'Комментарий',
        'start': 'Дата списания',
        'duration': 'Длительность',
        'obsidian_duration': 'Длительность (obsidian)',
        'obsidian_status': 'Статус (obsidian)',
        'obsidian_info': 'Информация Obsidian',
        'weekday': 'День недели',
        'duration_match': 'Совпадение',
        'date_only': 'Дата'
    }, inplace=True)

    click.secho(f'Информация по сотруднику {current_user} c {create_date_from} до {create_date_to}', fg='bright_green')

    # Выводим таблицу
    result_lines = _format_pivot_with_discrepancies(df1)
    for line in result_lines:
        if 'All' in line:
            click.secho(line, fg='bright_yellow')
        else:
            print(line)

    # Выводим расшифровку расхождений после таблицы
    if obsidian_only_tasks or tracker_discrepancies:
        _print_discrepancies_summary(obsidian_only_tasks, tracker_discrepancies)


def show_works_by_task(task_number: int, org_id: int, token: str, project: str):
    """
    Обработка и отображение трудоотчетов по задаче
    Args:
        task_number (int):          номер задачи
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
        project (str):              буквенный идентификатор проекта в трекере
    """
    answer = request_worklogs_by_task(task_number, org_id, token, project)
    df = (pd.json_normalize(answer))
    if df.empty:
        click.secho(f'Информация по задаче {task_number} не обнаружена.',
                    fg='bright_red')
        return
    if "comment" not in df.columns:
        df.insert(1, "comment", 'NaN')
    df1 = df[["issue.key", "createdBy.display", "id", "comment", "start", "duration", ]]
    df1["start"] = pd.to_datetime(df1["start"], utc=True).dt.tz_convert('Europe/Moscow').dt.to_period("D")
    df1["duration"] = df1["duration"].str.replace('P', '', regex=True, ).replace('T', '', regex=True, ).apply(
        parse).map(lambda x: x / 3600)
    df1.rename(columns={'issue.key': 'Номер задачи',
                        'createdBy.display': 'Автор отчёта',
                        'id': 'Номер трудоотчета',
                        'comment': 'Комментарий',
                        'start': 'Дата списания',
                        'duration': 'Длительность',
                        }, inplace=True)
    click.secho(
        f'Информация по задаче {project}-{task_number} \'{df["issue.display"].iloc[0]}\' ({df["issue.self"].iloc[0]})',
        fg='bright_green')
    click.secho(df1, fg='bright_yellow')


def duration_input() -> str:
    """
    Ввод длительности трудоотчета с проверкой ввода
    https://cloud.yandex.ru/docs/tracker/concepts/issues/patch-worklog
    Returns:
        str: значение затраченного времени в формате трекера (2h30m)
    """
    while True:
        text = click.prompt(
            "Введите новое значение затраченного времени в формате трекера (2h30m), "
            "на конце могут быть только h или m").replace(' ', '')
        try:
            int(text)
            text = f'{text}h'
        except ValueError:
            pass

        if text[-1] not in ["m", "h"]:
            click.echo("Исправьте вводимое время, формат не распознан")
            continue
        else:
            break
    return text


def valid_date_input() -> datetime:
    """
    Ввод даты трудоотчета с проверкой ввода
    Returns:
        datetime: возвращаем строку, все равно в запрос используется строка
    """
    global default_date
    valid_date = ""
    while True:
        try:
            valid_date = click.prompt("Введите дату в формате YYYY-MM-DD, либо число от 0 до 13 "
                                      "(0 - сегодня, 1 - вчера, 2 - позавчера и т.д.)", default=default_date)
            valid_date = str(datetime.datetime.strptime(valid_date, '%Y-%m-%d'))[:10]
            break
        except ValueError:
            try:
                num = int(valid_date)
                if num < 0 or num > 13:
                    click.secho("Цифра не валидна и не будет преобразована в дату", fg='bright_red')
                    continue
                else:
                    valid_date = str(datetime.date.today() - datetime.timedelta(days=num))[:10]
                    break
            except ValueError:
                pass
            click.secho("Дата не валидна!", fg='bright_red')
            continue
    click.secho(f"Итоговая дата: {valid_date}", fg='bright_green')
    default_date = valid_date
    return valid_date


def task_number_input(project: str) -> int:
    """
    Ввод номера задачи с проверкой ввода
    Args:
        project (str):  буквенный идентификатор проекта в трекере

    Returns:
        int: номер задачи
    """
    return click.prompt(f"Введите номер задачи в проекте '{project}' (только int)", type=int)


def worklog_number_input() -> int:
    """
    Ввод номера трудоотчета с проверкой ввода
    Returns:
        int: номер трудоотчета
    """
    return click.prompt("Введите номер трудоотчета (только int)", type=int)


def request_worklogs_by_date(create_date_from: str, create_date_to: str, current_user: str, org_id: int,
                             token: str) -> dict:
    """
    Получение трудоотчетов за интервал дат
    https://cloud.yandex.ru/docs/tracker/concepts/issues/get-worklog
    Args:
        create_date_from (str):     дата начала интервала для получения данных
        create_date_to (str):       дата окончания интервала для получения данных
        current_user (str):         активный пользователь для получения данных
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен

    Returns:
        dict:                         json
    """
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }
    data = {
        "createdBy": current_user,
        "start": {
            "from": f"{create_date_from}T00:00:00.000+0300",
            "to": f"{create_date_to}T23:59:59.999+0300"
        }
    }
    response = requests.post(
        f'https://api.tracker.yandex.net/v2/worklog/_search',
        headers=headers,
        data=json.dumps(data)
    )
    answer = json.loads(response.text)
    return answer


def request_worklogs_by_task(task_number: int, org_id: int, token: str, project: str) -> dict:
    """
    Получение трудоотчетов по задаче
    https://cloud.yandex.ru/docs/tracker/concepts/issues/issue-worklog
    Args:
        task_number (int):          номер задачи
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
        project (str):              буквенный идентификатор проекта в трекере

    Returns:
        dict:                        json
    """
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }

    response = requests.get(
        f'https://api.tracker.yandex.net/v2/issues/{project}-{task_number}/worklog',
        headers=headers,
    )
    answer = json.loads(response.text)
    return answer


def add_worklog_to_task(task_number: int, start_date: datetime, duration: str, comment: str, org_id: int, token: str,
                        project: str):
    """
    Добавление трудоотчета в задачу с указанием номера задачи, даты отчета, его длительности и комментария к нему
    https://cloud.yandex.ru/docs/tracker/concepts/issues/issue-worklog
    Args:
        comment (str):              комментарий к трудоотчету
        duration (str):             длительность трудоотчета в формате трекера
        start_date (datetime):           дата трудоотчета
        task_number (int):          номер задачи
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
        project (str):              буквенный идентификатор проекта в трекере
    """
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }
    data = {
        "start": start_date,
        "duration": f"PT{duration}",
        "comment": comment
    }
    response = requests.post(
        f'https://api.tracker.yandex.net/v3/issues/{project}-{task_number}/worklog',
        headers=headers,
        data=json.dumps(data),
    )
    if response.status_code == 201:
        click.echo(f"Трудоотчет в задаче {project}-{task_number} успешно создан ({response.status_code}).")
    else:
        click.echo(f"Не удалось создать трудоотчет в задаче {project}-{task_number} ({response.status_code}).")
        click.echo(f"{response.text}.")


def delete_worklogs_by_number(task_number: int, worklog_number: int, org_id: int, token: str, project: str):
    """
    Удаление трудоотчета по номеру задачи и номеру трудоотчета
    https://cloud.yandex.ru/docs/tracker/concepts/issues/delete-worklog
    Args:
        task_number (int):          номер задачи
        worklog_number (int):       номер отчета о трудозатратах
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
        project (str):              буквенный идентификатор проекта в трекере
    """
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }
    response = requests.delete(
        f'https://api.tracker.yandex.net/v2/issues/{project}-{task_number}/worklog/{worklog_number}',
        headers=headers, )
    if response.status_code == 204:
        click.echo(f"Трудоотчет в задаче {project}-{task_number} успешно удален ({response.status_code}).")
    else:
        click.echo(f"Не удалось удалить трудоотчет в задаче {project}-{task_number} ({response.status_code}).")
        click.echo(f"{response.text}.")


def change_worklogs_by_number(task_number: int, worklog_number: int, new_duration: str, org_id: int, token: str,
                              project: str, new_comment: str = ''):
    """
    Изменение трудоотчета по номеру задачи и номеру трудоотчета
    https://cloud.yandex.ru/docs/tracker/concepts/issues/patch-worklog
    Args:
        task_number (int):          номер задачи
        worklog_number (int):       номер отчета о трудозатратах
        new_duration (str):         длительность нового трудоотчета в формате трекера
        org_id (int):               идентификатор организации из трекера
        token (str):                IAM токен
        project (str):              буквенный идентификатор проекта в трекере
        new_comment (str):          новый комментарий к трудоотчету
    """
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }
    params = {
        "duration": f"PT{new_duration}"
    }
    if len(new_comment) > 0:
        params["comment"] = f"{new_comment}"

    response = requests.patch(
        f'https://api.tracker.yandex.net/v2/issues/{project}-{task_number}/worklog/{worklog_number}',
        headers=headers,
        data=json.dumps(params),
    )

    if response.status_code == 200:
        click.echo(f"Трудоотчет в задаче {project}-{task_number} успешно изменен ({response.status_code}).")
    else:
        click.echo(f"Не удалось изменить трудоотчет в задаче {project}-{task_number} ({response.status_code}).")
        click.echo(f"{response.text}.")


def get_user_issues(username, org_id: int, token: str):
    """
    Получаем задачи пользователя через REST API
    """
    session = requests.Session()
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }
    json = {
        "filter": {
            "queue": tracker_project_id,
            "assignee": username,
            "status": tracker_issue_statuses
        }
    }
    session.headers.update(headers)

    try:
        response = session.post('https://api.tracker.yandex.net/v3/issues/_search', json=json)
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при получении задач: {e}")
        return []


def get_task_name_by_key(token: str, org_id: int, task_key: int) -> str:
    """
    Получает название задачи по её ключу из Yandex Tracker

    Args:
        token (str): IAM-токен для доступа к API
        org_id (int): ID организации в Yandex Tracker
        task_key (str): Ключ задачи (например, EDWH-123)

    Returns:
        str: Название задачи или сообщение об ошибке
    """
    # Формируем URL запроса
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Org-ID': f'{org_id}',
    }
    try:
        # Отправляем GET-запрос
        response = requests.get(
            f"https://api.tracker.yandex.net/v2/issues/{tracker_project_id}-{task_key}",
            headers=headers
        )

        # Проверяем статус ответа
        if response.status_code == 200:
            # Парсим JSON и получаем название задачи
            data = response.json()
            return data.get("summary", "Название не найдено")
        else:
            return f"Ошибка получения данных: {response.status_code}"

    except requests.exceptions.RequestException as e:
        return f"Произошла ошибка: {str(e)}"


def parse_obsidian_tasks(date_from, date_to, obsidian_vault_path: str = None):
    """
    Парсит задачи из Obsidian за указанный период во всех папках хранилища
    Возвращает словарь {дата: {task_id: {'pomodoros': int, 'completion_date': str, 'status': str}}}
    """

    def clean_description(text):
        # 1. Убираем task_id в начале (формат БУКВЫ-ЦИФРЫ)
        text = re.sub(r'^[A-Z]+-\d+\s*', '', text)
        # 2. Убираем эмодзи помидорок [🍅::N], [d::N], [::N]
        text = re.sub(r'\[(?:🍅|d)?::?\d+(?:\.\d+)?\]', '', text)
        # 3. Убираем временные метки (@2024-12-02 12:00)
        text = re.sub(r'\(@\d{4}-\d{2}-\d{2} \s*\d{2}:\d{2}\)', '', text)
        # 4. Убираем дни недели в скобках (Вт., Пт.)
        text = re.sub(r'\([А-Яа-яЁёA-Za-z\.,\s]+\)', '', text)
        # 5. Убираем даты 📅 YYYY-MM-DD
        text = re.sub(r'📅 \d{4}-\d{2}-\d{2}', '', text)
        # 6. Убираем отметки выполнения ✅ YYYY-MM-DD
        text = re.sub(r'✅ \d{4}-\d{2}-\d{2}', '', text)
        # 7. Убираем лишние пробелы, скобки, дефисы
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'^\s*[-\s]*\s*', '', text)
        text = re.sub(r'\s*[-\s]*\s*$', '', text)

        return text

    tasks_dict = {}

    # Конвертируем даты в datetime
    try:
        if isinstance(date_from, str):
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        elif hasattr(date_from, 'strftime'):
            start_date = date_from
        else:
            print(f"Неизвестный формат date_from: {type(date_from)}")
            return {}

        if isinstance(date_to, str):
            end_date = datetime.strptime(date_to, "%Y-%m-%d")
        elif hasattr(date_to, 'strftime'):
            end_date = date_to
        else:
            print(f"Неизвестный формат date_to: {type(date_to)}")
            return {}
    except Exception as e:
        print(f"Ошибка при преобразовании дат: {e}")
        return {}

    # Рекурсивно ищем все markdown файлы в хранилище
    if obsidian_vault_path:
        vault_path = Path(obsidian_vault_path)
        if not vault_path.exists():
            print(f"Путь к хранилищу не существует: {obsidian_vault_path}")
            return {}

        # Ищем все .md файлы рекурсивно
        md_files = list(vault_path.rglob("*.md"))
        log_message(f"Найдено {len(md_files)} markdown файлов в хранилище", "INFO")
    else:
        log_message("Не указан путь к хранилищу Obsidian", "ERROR")
        return {}

    # Определяем паттерны для поиска task_id
    # Поддерживаем различные префиксы: TN-, EDWH-, и другие буквенно-цифровые комбинации
    task_id_patterns = [
        r'([A-Z]{2,}-\d+)',      # EDWH-123, TN-456 (2+ буквы, дефис, цифры)
        r'([A-Z]+-\d+)',         # T-123, A-456 (1+ буквы, дефис, цифры)
    ]

    # Проходим по всем файлам
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            pattern = r'- \[([ x])\]\s+([A-Z]+-\d+)\s*-\s*(.+)'
            task_strings = re.findall(pattern, content)

            for status_char, task_part, task_desc in task_strings:
                # Ищем task_id в начале строки задачи
                task_id = None
                for pattern in task_id_patterns:
                    match = re.match(pattern, task_part.strip())
                    if match:
                        task_id = match.group(1)
                        break

                if not task_id:
                    # Если task_id так и не нашли, пропускаем эту задачу
                    continue

                status = 'completed' if status_char == 'x' else 'pending'

                # Ищем количество помидоров в описании задачи
                pomodoro_match = re.search(r'\[🍅::(\d+)\]', task_desc)
                pomodoros = int(pomodoro_match.group(1)) if pomodoro_match else 0

                # Ищем дату выполнения (если есть)
                completion_match = re.search(r'✅\s*(\d{4}-\d{2}-\d{2})', task_desc)
                completion_date = completion_match.group(1) if completion_match else None

                # Ищем дату планирования
                scheduled_match = re.search(r'📅\s*(\d{4}-\d{2}-\d{2})', task_desc)
                scheduled_date = scheduled_match.group(1) if scheduled_match else None

                # Ищем дедлайн (⏳ или другие символы)
                deadline_match = re.search(r'[⏳📌]\s*(\d{4}-\d{2}-\d{2})', task_desc)
                deadline_date = deadline_match.group(1) if deadline_match else None

                # Ищем время (если есть в формате @YYYY-MM-DD HH:MM)
                time_match = re.search(r'@(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', task_desc)
                time_info = time_match.group(1) if time_match else None

                # Определяем, какую дату использовать для группировки
                use_date = None

                # Приоритет дат для группировки:
                use_date = scheduled_date

                # Проверяем, попадает ли дата в запрашиваемый диапазон
                try:
                    task_date = datetime.strptime(use_date, "%Y-%m-%d")
                    if task_date < start_date or task_date > end_date:
                        continue
                except ValueError:
                    continue
                # 1 помидор = 30 минут
                duration_hours = pomodoros * 0.5

                # описание задачи
                description = clean_description(clean_description(task_desc.strip()))

                if use_date not in tasks_dict:
                    tasks_dict[use_date] = {}

                # Если задача с таким ID уже существует, объединяем помидоры
                if task_id in tasks_dict[use_date]:
                    existing_task = tasks_dict[use_date][task_id]
                    existing_task['duration_hours'] += duration_hours
                    # Обновляем статус, если новая задача выполнена
                    if status == 'completed':
                        existing_task['status'] = 'completed'
                        existing_task['completion_date'] = completion_date or existing_task['completion_date']
                else:
                    # Собираем дополнительную информацию о файле
                    tasks_dict[use_date][task_id] = {
                        'duration_hours': duration_hours,
                        'completion_date': completion_date,
                        'scheduled_date': scheduled_date,
                        'deadline_date': deadline_date,
                        'time_info': time_info,
                        'status': status,
                        'description': task_desc.strip(),
                        'file_path': str(md_file.relative_to(vault_path)),
                        'vault_path': str(vault_path),
                        'source_file': md_file.name,
                        'full_task_line': f"- [{status_char}] {task_id} - {task_desc.strip()}",
                        'description': description
                    }

        except UnicodeDecodeError:
            print(f"Ошибка кодировки в файле: {md_file}")
            continue
        except Exception as e:
            print(f"Ошибка при чтении файла {md_file}: {e}")
            continue

    # Сортируем по датам для удобства
    sorted_tasks = {k: tasks_dict[k] for k in sorted(tasks_dict.keys())}

    # Считаем общее количество уникальных задач
    unique_tasks = set()
    for date_tasks in sorted_tasks.values():
        unique_tasks.update(date_tasks.keys())


    return sorted_tasks


if __name__ == '__main__':
    main()
