#!/bin/bash

SERVER=inv
PROJECT_NAME=obsidian-utils

export VERSION=$(cat .version 2>/dev/null || echo "1.0.1") && NEW_VERSION=$(echo $VERSION | awk -F. '{$NF+=1}1' OFS=.) && echo $NEW_VERSION > .version && export VERSION=$NEW_VERSION
echo "VERSION=$VERSION"

# сборка
docker build -t registry.gitlab.com/my6145916/$PROJECT_NAME:$VERSION .
sudo docker push registry.gitlab.com/my6145916/$PROJECT_NAME:$VERSION

echo "Обновляем docker-compose"
scp docker-compose-deploy.yaml ${SERVER}:/srv/$PROJECT_NAME
scp .env ${SERVER}:/srv/$PROJECT_NAME

echo "Запуск приложения ${VERSION}"
ssh -t ${SERVER} "cd /srv/$PROJECT_NAME && export VERSION=${VERSION} && docker compose -f docker-compose-deploy.yaml down && docker compose -f docker-compose-deploy.yaml up -d"
