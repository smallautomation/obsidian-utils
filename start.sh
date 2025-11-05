#!/bin/bash

PROJECT_NAME=obsidian-utils

export VERSION=$(cat .version 2>/dev/null || echo "1.0.1")
echo $VERSION

docker run --rm --name $PROJECT_NAME -it --env-file .env -v /srv/obsidian/notes:/app/notes:ro registry.gitlab.com/my6145916/$PROJECT_NAME:$VERSION
