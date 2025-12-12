from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import yaml
from pathlib import Path

from sync.reconciliation import ReconciliationService
from sync.balance_checker import BalanceChecker
from utils.logger import setup_logger

logger = setup_logger(__name__)

class TelegramBot:
    def __init__(self, config_path: str):
        self.config_path = config_path
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.bot_token = self.config['telegram']['bot_token']
        self.admin_ids = self.config['telegram']['admin_ids']
        self.reconciliation = ReconciliationService(config_path)
        self.balance_checker = BalanceChecker(config_path)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        if update.effective_user.id not in self.admin_ids:
            await update.message.reply_text("У вас нет доступа к этому боту.")
            return
        
        await update.message.reply_text(
            "Бот синхронизации Obsidian с трекерами запущен.\n\n"
            "Доступные команды:\n"
            "/reconcile [month] - сверка за месяц (формат: YYYY-MM)\n"
            "/balance - проверка баланса по проектам\n"
            "/sync [task_id] - синхронизация конкретной задачи\n"
            "/status - статус службы синхронизации"
        )
    
    async def reconcile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды сверки"""
        if update.effective_user.id not in self.admin_ids:
            return
        
        month_str = context.args[0] if context.args else None
        
        if month_str:
            try:
                year, month = map(int, month_str.split('-'))
                report = await self.reconciliation.reconcile_month(year, month)
                
                # Форматирование отчета
                message = self._format_reconciliation_report(report)
                await update.message.reply_text(message, parse_mode='Markdown')
                
            except Exception as e:
                await update.message.reply_text(f"Ошибка: {e}")
        else:
            # Сверка за текущий месяц
            from datetime import datetime
            now = datetime.now()
            report = await self.reconciliation.reconcile_month(now.year, now.month)
            message = self._format_reconciliation_report(report)
            await update.message.reply_text(message, parse_mode='Markdown')
    
    def _format_reconciliation_report(self, report: dict) -> str:
        """Форматирование отчета для Telegram"""
        lines = [
            f"*Сверка за {report['month']}*",
            f"Расхождения: {report['total_discrepancies']}",
            f"Общая разница: {report['total_hours_difference']:.2f} ч",
            ""
        ]
        
        if report['discrepancies']:
            lines.append("*Детали:*")
            for d in report['discrepancies']:
                lines.append(
                    f"{d['project']}: Obsidian {d['obsidian_hours']:.1f}ч vs "
                    f"Tracker {d['tracker_hours']:.1f}ч "
                    f"(разница: {d['difference']:+.1f}ч)"
                )
        
        return "\n".join(lines)
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка баланса проектов"""
        if update.effective_user.id not in self.admin_ids:
            return
        
        imbalances = await self.balance_checker.check_projects_balance()
        
        if imbalances:
            message = self._format_balance_message(imbalances)
        else:
            message = "Баланс по всем проектам в норме ?"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    def _format_balance_message(self, imbalances: list) -> str:
        """Форматирование сообщения о дисбалансе"""
        lines = ["*Дисбаланс по проектам:*"]
        
        for imb in imbalances:
            lines.append(
                f"?? {imb['project']}: {imb['current_balance']:.1f}ч "
                f"(цель: {imb['target_balance']:.1f}ч, "
                f"разница: {imb['difference']:+.1f}ч)"
            )
        
        return "\n".join(lines)
    
    def run(self):
        """Запуск бота"""
        application = Application.builder().token(self.bot_token).build()
        
        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("reconcile", self.reconcile_command))
        application.add_handler(CommandHandler("balance", self.balance_command))
        
        logger.info("Starting Telegram bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    config_path = "config/config.yaml"
    bot = TelegramBot(config_path)
    bot.run()

if __name__ == "__main__":
    main()