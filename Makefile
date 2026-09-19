# ============================================================
# Makefile — Tree Content Generator
# ============================================================
#
# Alvos:
#   make help              Lista os alvos (padrão)
#   make install           Instala tudo (pip + sistema)
#   make install-pip       Só pacotes Python (pip)
#   make install-sistema   Só binários de sistema (apt/dnf/pacman)
#   make check             Diagnóstico do ambiente
#   make test              Roda os testes de fumaça
#   make run               Executa o gerador interativo
#   make venv              Cria .venv/
#   make venv-shell        Abre shell dentro do .venv
#   make clean             Remove caches e saída gerada
#   make clean-venv        Remove o .venv/
#   make uninstall         Remove pacotes Python do projeto
# ============================================================

# Usa bash com set -e e "one shell" — permite if...fi de várias linhas
# sem precisar de '\' no fim de cada linha, e para na primeira falha.
SHELL := /bin/bash
.SHELLFLAGS := -ec
.ONESHELL:

# ---------- Configurações ----------
PYTHON       ?= python3
PIP          ?= $(PYTHON) -m pip
VENV_DIR     ?= .venv
VENV_PY      ?= $(VENV_DIR)/bin/python
VENV_PIP     ?= $(VENV_DIR)/bin/pip

SCRIPT       := geradordepastasearquivos.py
REQS         := requirements.txt
INSTALADOR   := instalar_opcionais.sh

SAIDA_PADRAO := estrutura_completa.md
SAIDA_DIR    := estrutura_completa_arquivos

# Cores (desligadas se stdout não for terminal)
ifeq ($(shell [ -t 1 ] && echo sim),sim)
    C_OK  := \033[92m
    C_ER  := \033[91m
    C_AV  := \033[93m
    C_IN  := \033[94m
    C_BO  := \033[1m
    C_END := \033[0m
else
    C_OK  :=
    C_ER  :=
    C_AV  :=
    C_IN  :=
    C_BO  :=
    C_END :=
endif

.DEFAULT_GOAL := help
.PHONY: help install install-pip install-sistema check verificar run test \
        clean clean-venv uninstall venv venv-shell deps-sistema

# ============================================================
# Ajuda
# ============================================================
help:
	@echo -e "$(C_BO)Tree Content Generator — alvos disponíveis$(C_END)"
	@echo
	@echo -e "$(C_IN)Instalação$(C_END)"
	@echo "  make install             Instala tudo (pip + sistema)"
	@echo "  make install-pip         Só pacotes Python (via pip)"
	@echo "  make install-sistema     Só binários de sistema"
	@echo "  make deps-sistema        Alias de install-sistema"
	@echo
	@echo -e "$(C_IN)Ambiente virtual$(C_END)"
	@echo "  make venv                Cria .venv/"
	@echo "  make venv-shell          Abre shell dentro do .venv"
	@echo
	@echo -e "$(C_IN)Verificação e uso$(C_END)"
	@echo "  make check               Diagnóstico do ambiente"
	@echo "  make test                Roda os testes de fumaça"
	@echo "  make run                 Executa o gerador interativo"
	@echo
	@echo -e "$(C_IN)Manutenção$(C_END)"
	@echo "  make clean               Remove caches e saída gerada"
	@echo "  make clean-venv          Remove o .venv/"
	@echo "  make uninstall           Remove pacotes Python do projeto"
	@echo

# ============================================================
# Instalação completa
# ============================================================
install: install-pip install-sistema
	@echo
	@echo -e "$(C_OK)✓ Instalação completa concluída$(C_END)"
	@echo "  Próximo:  make check   ou   make run"

# ============================================================
# Instalação — pip
# ============================================================
install-pip:
	@test -f "$(INSTALADOR)" || (echo -e "$(C_ER)✗ $(INSTALADOR) não encontrado$(C_END)"; exit 1)
	@echo -e "$(C_IN)ℹ️  Instalando pacotes Python (requirements.txt)$(C_END)"
	@if [ -d "$(VENV_DIR)" ]; then
	@	echo "   Usando venv em $(VENV_DIR)"
	@	$(VENV_PIP) install --upgrade pip
	@	$(VENV_PIP) install -r $(REQS)
	@else
	@	echo "   Sem venv; usando pip do sistema (modo --user)"
	@	if $(PIP) install --user -r $(REQS); then
	@		echo -e "$(C_OK)   ✓ instalado (--user)$(C_END)"
	@	elif $(PIP) install --user --break-system-packages -r $(REQS); then
	@		echo -e "$(C_OK)   ✓ instalado (--user --break-system-packages)$(C_END)"
	@	else
	@		echo -e "$(C_ER)   ✗ pip falhou.$(C_END)"
	@		echo "     Tente:  make venv && make install-pip"
	@		exit 1
	@	fi
	@fi
	@echo -e "$(C_OK)✓ Pacotes Python instalados$(C_END)"

# ============================================================
# Instalação — sistema
# ============================================================
install-sistema:
	@test -f "$(INSTALADOR)" || (echo -e "$(C_ER)✗ $(INSTALADOR) não encontrado$(C_END)"; exit 1)
	@echo -e "$(C_IN)ℹ️  Instalando binários de sistema$(C_END)"
	@./$(INSTALADOR) --sistema
	@echo -e "$(C_OK)✓ Binários de sistema processados$(C_END)"

deps-sistema: install-sistema

# ============================================================
# Verificação
# ============================================================
check:
	@test -f "$(INSTALADOR)" || (echo -e "$(C_ER)✗ $(INSTALADOR) não encontrado$(C_END)"; exit 1)
	@echo -e "$(C_BO)Verificando o ambiente...$(C_END)"
	@./$(INSTALADOR) --listar
	@echo
	@echo -e "$(C_IN)ℹ️  Verificando o próprio gerador$(C_END)"
	@if [ -f "$(SCRIPT)" ]; then
	@	echo -e "$(C_OK)  ✓ $(SCRIPT) presente$(C_END)"
	@	if $(PYTHON) -m py_compile $(SCRIPT); then
	@		echo -e "$(C_OK)  ✓ $(SCRIPT) compila sem erro de sintaxe$(C_END)"
	@		rm -rf __pycache__
	@	else
	@		echo -e "$(C_ER)  ✗ $(SCRIPT) tem erro de sintaxe$(C_END)"
	@		exit 1
	@	fi
	@else
	@	echo -e "$(C_ER)  ✗ $(SCRIPT) não encontrado$(C_END)"
	@	exit 1
	@fi
	@if [ -d "$(VENV_DIR)" ]; then
	@	echo -e "$(C_OK)  ✓ venv presente ($(VENV_DIR))$(C_END)"
	@else
	@	echo -e "$(C_AV)  ⚠️  sem venv (opcional)$(C_END)"
	@fi

verificar: check

# ============================================================
# Testes
# ============================================================
test:
	@test -f "$(SCRIPT)" || (echo -e "$(C_ER)✗ $(SCRIPT) não encontrado$(C_END)"; exit 1)
	@echo -e "$(C_BO)Rodando testes de fumaça...$(C_END)"
	@$(PYTHON) -m tests.testes_smoke

# ============================================================
# Uso
# ============================================================
run:
	@test -f "$(SCRIPT)" || (echo -e "$(C_ER)✗ $(SCRIPT) não encontrado$(C_END)"; exit 1)
	@echo -e "$(C_IN)ℹ️  Executando o gerador interativo...$(C_END)"
	@if [ -d "$(VENV_DIR)" ] && [ -x "$(VENV_PY)" ]; then
	@	$(VENV_PY) $(SCRIPT) $(ARGS)
	@else
	@	$(PYTHON) $(SCRIPT) $(ARGS)
	@fi

# ============================================================
# Ambiente virtual
# ============================================================
venv:
	@if [ -d "$(VENV_DIR)" ]; then
	@	echo -e "$(C_AV)⚠️  $(VENV_DIR) já existe; nada a fazer.$(C_END)"
	@else
	@	echo -e "$(C_IN)ℹ️  Criando ambiente virtual em $(VENV_DIR)$(C_END)"
	@	$(PYTHON) -m venv $(VENV_DIR)
	@	$(VENV_PIP) install --upgrade pip
	@	echo -e "$(C_OK)✓ venv criado$(C_END)"
	@	echo "  Ative com:  source $(VENV_DIR)/bin/activate"
	@fi

venv-shell:
	@test -d "$(VENV_DIR)" || (echo -e "$(C_ER)✗ $(VENV_DIR) não existe. Rode: make venv$(C_END)"; exit 1)
	@echo -e "$(C_IN)ℹ️  Abrindo shell dentro do $(VENV_DIR)$(C_END)"
	@echo "  (digite 'exit' para sair)"
	@echo
	@bash --rcfile <(printf 'source "%s/bin/activate"\nPS1="(venv) $$PS1"\n' "$(VENV_DIR)")

# ============================================================
# Limpeza
# ============================================================
clean:
	@echo -e "$(C_IN)ℹ️  Limpando caches e arquivos gerados...$(C_END)"
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
	@rm -f $(SAIDA_PADRAO) 2>/dev/null || true
	@rm -rf $(SAIDA_DIR) 2>/dev/null || true
	@rm -f estrutura*.md 2>/dev/null || true
	@rm -rf estrutura*_arquivos 2>/dev/null || true
	@echo -e "$(C_OK)✓ Limpo$(C_END)"

clean-venv:
	@echo -e "$(C_AV)⚠️  Removendo $(VENV_DIR)/ (irreversível)$(C_END)"
	@rm -rf $(VENV_DIR)
	@echo -e "$(C_OK)✓ venv removido$(C_END)"

# ============================================================
# Desinstalação
# ============================================================
uninstall:
	@echo -e "$(C_IN)ℹ️  Removendo pacotes Python instalados pelo projeto$(C_END)"
	@if [ -d "$(VENV_DIR)" ]; then
	@	$(VENV_PIP) uninstall -y pycdlib zstandard py7zr chardet 2>/dev/null || true
	@else
	@	$(PIP) uninstall -y pycdlib zstandard py7zr chardet 2>/dev/null || \
	@	$(PIP) uninstall -y --break-system-packages pycdlib zstandard py7zr chardet 2>/dev/null || true
	@fi
	@echo -e "$(C_OK)✓ Pacotes Python removidos$(C_END)"
	@echo "  Binários de sistema não foram tocados (remova manualmente se quiser)"
