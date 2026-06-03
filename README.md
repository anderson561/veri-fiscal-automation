# 📑 veri-fiscal-automation

Automação inteligente desenvolvida para verificar e analisar pendências fiscais nos relatórios federais do **E-CAC**, gerando relatórios consolidados em PDF.

O sistema realiza a leitura automatizada e exporta 3 documentos fundamentais:
1. **Omissão:** Relatório de declarações omitidas.
2. **Pendências:** Situações cadastrais e operacionais pendentes.
3. **Débitos:** Valores e guias de débitos federais em aberto.

---

## 🛠️ Tecnologias Utilizadas

Este projeto foi construído utilizando uma arquitetura híbrida de alto desempenho:
- **Python:** Motor principal responsável pela lógica de raspagem, automação e geração dos relatórios PDF.
- **Node.js / JavaScript:** Módulos auxiliares de processamento de dados e scripts de suporte.
- **PyInstaller:** Utilizado para compilar a automação em um executável nativo (`.exe`), facilitando o uso para o usuário final sem necessidade de instalar interpretadores.

---

## 📁 Estrutura do Projeto

```text
veri-fiscal-automation/
├── src/                # Código-fonte principal da automação
├── tests/              # Testes unitários e de integração
├── build.bat           # Script automatizado para compilar o projeto
├── executar.bat        # Script para execução rápida em ambiente local
├── requirements.txt    # Dependências do ecossistema Python
├── package.json        # Dependências do ecossistema Node.js
└── VeriFiscal.spec     # Arquivo de configuração do PyInstaller
