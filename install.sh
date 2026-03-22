#!/bin/bash
# ============================================
#  CCTV Console — Автоматическая установка
#  Система видеонаблюдения с распознаванием лиц
# ============================================

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_logo() {
    echo -e "${CYAN}"
    echo "  ██████╗ ██████╗████████╗██╗   ██╗"
    echo " ██╔════╝██╔════╝╚══██╔══╝██║   ██║"
    echo " ██║     ██║        ██║   ██║   ██║"
    echo " ██║     ██║        ██║   ╚██╗ ██╔╝"
    echo " ╚██████╗╚██████╗   ██║    ╚████╔╝ "
    echo "  ╚═════╝ ╚═════╝   ╚═╝     ╚═══╝  "
    echo -e "${NC}"
    echo -e "${GREEN} Система видеонаблюдения с распознаванием лиц${NC}"
    echo ""
}

log_info()    { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
log_error()   { echo -e "${RED}[✗]${NC} $1"; }
log_step()    { echo -e "${BLUE}[→]${NC} $1"; }

# Проверка root
check_root() {
    if [ "$EUID" -eq 0 ]; then
        log_warn "Скрипт запущен от root. Рекомендуется запускать от обычного пользователя."
        read -p "Продолжить? (y/N): " confirm
        [ "$confirm" != "y" ] && [ "$confirm" != "Y" ] && exit 0
    fi
}

# Определение ОС и архитектуры
detect_system() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    case "$ARCH" in
        aarch64|arm64) ARCH_NAME="ARM64 (Raspberry Pi / ARM)" ;;
        x86_64|amd64)  ARCH_NAME="x86_64" ;;
        *)             ARCH_NAME="$ARCH" ;;
    esac

    log_info "Система: $OS ($ARCH_NAME)"
}

# Проверка зависимостей
check_dependencies() {
    log_step "Проверка зависимостей..."

    local missing=()

    if ! command -v docker &>/dev/null; then
        missing+=("docker")
    fi

    if ! docker compose version &>/dev/null 2>&1; then
        if ! command -v docker-compose &>/dev/null; then
            missing+=("docker-compose")
        fi
    fi

    if ! command -v git &>/dev/null; then
        missing+=("git")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Не установлены: ${missing[*]}"
        echo ""
        log_step "Установка недостающих компонентов..."
        install_dependencies "${missing[@]}"
    else
        log_info "Все зависимости установлены"
    fi
}

# Установка зависимостей
install_dependencies() {
    # Определяем пакетный менеджер
    if command -v apt-get &>/dev/null; then
        PKG_MANAGER="apt"
    elif command -v dnf &>/dev/null; then
        PKG_MANAGER="dnf"
    elif command -v yum &>/dev/null; then
        PKG_MANAGER="yum"
    else
        log_error "Не удалось определить пакетный менеджер. Установите вручную: $*"
        exit 1
    fi

    for dep in "$@"; do
        case "$dep" in
            docker)
                log_step "Установка Docker..."
                curl -fsSL https://get.docker.com | sh
                sudo systemctl enable docker
                sudo systemctl start docker
                # Добавляем текущего пользователя в группу docker
                if [ "$EUID" -ne 0 ]; then
                    sudo usermod -aG docker "$USER"
                    log_warn "Пользователь добавлен в группу docker. Может потребоваться перелогиниться."
                fi
                log_info "Docker установлен"
                ;;
            docker-compose)
                log_step "Docker Compose устанавливается вместе с Docker..."
                ;;
            git)
                log_step "Установка git..."
                sudo $PKG_MANAGER install -y git
                log_info "Git установлен"
                ;;
        esac
    done
}

# Выбор директории установки
choose_install_dir() {
    echo ""
    echo -e "${CYAN}Куда установить CCTV?${NC}"
    echo ""

    # Предлагаем варианты
    local default_dir="/opt/cctv"
    local suggestions=()

    # Проверяем доступные диски
    if [ -d "/srv/apps" ]; then
        suggestions+=("/srv/apps/CCTV")
        log_info "Найден /srv/apps (NVMe/SSD)"
    fi

    suggestions+=("$default_dir")
    suggestions+=("$HOME/CCTV")

    for i in "${!suggestions[@]}"; do
        echo "  $((i+1))) ${suggestions[$i]}"
    done
    echo "  $((${#suggestions[@]}+1))) Указать свой путь"
    echo ""

    read -p "Выберите вариант [1]: " choice
    choice=${choice:-1}

    if [ "$choice" -le "${#suggestions[@]}" ] 2>/dev/null; then
        INSTALL_DIR="${suggestions[$((choice-1))]}"
    else
        read -p "Введите путь: " INSTALL_DIR
    fi

    # Создаём директорию если нужно
    if [ ! -d "$(dirname "$INSTALL_DIR")" ]; then
        sudo mkdir -p "$(dirname "$INSTALL_DIR")"
        sudo chown "$USER:$USER" "$(dirname "$INSTALL_DIR")"
    fi

    log_info "Директория установки: $INSTALL_DIR"
}

# Клонирование или обновление репозитория
clone_or_update() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        log_step "Обновление существующей установки..."
        cd "$INSTALL_DIR"
        git pull origin main
        log_info "Обновлено до последней версии"
    else
        log_step "Клонирование репозитория..."
        git clone https://github.com/LaNadKo/CCTV.git "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        log_info "Репозиторий склонирован"
    fi
}

# Генерация .env
setup_env() {
    if [ -f "$INSTALL_DIR/.env" ]; then
        log_warn "Файл .env уже существует"
        read -p "Перезаписать? (y/N): " overwrite
        [ "$overwrite" != "y" ] && [ "$overwrite" != "Y" ] && return
    fi

    log_step "Настройка конфигурации..."

    # Генерация секретов
    JWT_SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | xxd -p | tr -d '\n' | head -c 64)
    PROCESSOR_KEY=$(openssl rand -hex 24 2>/dev/null || head -c 48 /dev/urandom | xxd -p | tr -d '\n' | head -c 48)
    DB_PASSWORD=$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | xxd -p | tr -d '\n' | head -c 32)

    # Определяем IP
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    echo ""
    read -p "Домен или IP сервера [$LOCAL_IP]: " DOMAIN
    DOMAIN=${DOMAIN:-$LOCAL_IP}

    read -p "Пароль PostgreSQL [автогенерация]: " input_db_pass
    DB_PASSWORD=${input_db_pass:-$DB_PASSWORD}

    cat > "$INSTALL_DIR/.env" << ENVEOF
# CCTV Console Configuration
# Сгенерировано автоматически $(date '+%Y-%m-%d %H:%M')

DOMAIN=$DOMAIN
POSTGRES_USER=cctv
POSTGRES_PASSWORD=$DB_PASSWORD
POSTGRES_DB=cctv
JWT_SECRET=$JWT_SECRET
PROCESSOR_API_KEY=$PROCESSOR_KEY
ENABLE_EMBEDDED_DETECTOR=false
DEBUG=false
TOTP_ENCRYPTION_KEY=
RECORDINGS_PATH=./data/recordings
SNAPSHOTS_PATH=./data/snapshots
ENVEOF

    log_info "Конфигурация сохранена в .env"
}

# Запуск сервисов
start_services() {
    log_step "Запуск сервисов..."

    cd "$INSTALL_DIR"

    # Останавливаем старое если есть
    docker compose down 2>/dev/null || true

    # Собираем и запускаем
    docker compose up -d --build db backend mediamtx

    echo ""
    log_step "Ожидание запуска сервисов..."

    # Ждём готовности бэкенда
    local retries=30
    while [ $retries -gt 0 ]; do
        if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
            break
        fi
        retries=$((retries-1))
        sleep 2
        echo -ne "\r${BLUE}[→]${NC} Ожидание бэкенда... ($retries)"
    done
    echo ""

    if [ $retries -eq 0 ]; then
        log_warn "Бэкенд долго запускается. Проверьте логи: docker compose logs backend"
    else
        log_info "Бэкенд готов"
    fi
}

# Вывод итогов
print_summary() {
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    echo ""
    echo -e "${CYAN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ CCTV Console успешно установлен!${NC}"
    echo -e "${CYAN}════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BLUE}API:${NC}         http://$LOCAL_IP:8000"
    echo -e "  ${BLUE}Swagger:${NC}     http://$LOCAL_IP:8000/docs"
    echo -e "  ${BLUE}RTSP:${NC}        rtsp://$LOCAL_IP:8554"
    echo ""
    echo -e "  ${YELLOW}Логин:${NC}       admin"
    echo -e "  ${YELLOW}Пароль:${NC}      admin"
    echo -e "  ${YELLOW}(при первом входе потребуется сменить пароль)${NC}"
    echo ""
    echo -e "  ${BLUE}Директория:${NC}  $INSTALL_DIR"
    echo ""
    echo -e "  ${CYAN}Полезные команды:${NC}"
    echo -e "  ./scripts/start-server.sh   — запуск сервера"
    echo -e "  ./scripts/stop-server.sh    — остановка"
    echo -e "  ./scripts/logs.sh           — просмотр логов"
    echo -e "  ./scripts/logs.sh backend   — логи бэкенда"
    echo -e "  ./scripts/reset-db.sh       — сброс базы данных"
    echo ""
    echo -e "  ${CYAN}Подключение клиентов:${NC}"
    echo -e "  В Desktop/Mobile приложении укажите URL сервера:"
    echo -e "  ${GREEN}http://$LOCAL_IP:8000${NC}"
    echo ""
}

# ============================================
#  MAIN
# ============================================

print_logo
check_root
detect_system
check_dependencies
choose_install_dir
clone_or_update
setup_env
chmod +x "$INSTALL_DIR"/scripts/*.sh
start_services
print_summary
