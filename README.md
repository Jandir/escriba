<p align="center">
  <img src="logo.png" alt="Escriba Logo" width="220">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Versão-2.4.7-blue?style=for-the-badge" alt="Versão">
  <img src="https://img.shields.io/badge/Python-3.13+-ffd343?style=for-the-badge&logo=python&logoColor=black" alt="Python">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Licença-MIT-green?style=for-the-badge" alt="Licença">
  <img src="https://img.shields.io/badge/Target-NotebookLM-6f42c1?style=for-the-badge&logo=google" alt="NotebookLM">
</p>

# Escriba: Video-to-Knowledge ETL Pipeline
### O Orquestrador de Inteligência para YouTube

**Escriba** é um pipeline de extração, higienização via LLM e estruturação de dados não estruturados de vídeo para bases de conhecimento (RAG/NotebookLM).

Diferente de simples scripts de download, o Escriba atua como um **Escriba Digital**: ele não apenas "baixa" o conteúdo, ele o interpreta, deduplica roll-ups de legendas automáticas e segmenta semanticamente os tópicos para criar documentos `.md` de altíssima fidelidade.

Ativos de vídeo corporativo (como treinamentos, conferências e reuniões) frequentemente se tornam "dados mortos" devido à dificuldade de busca e consulta. O Escriba resolve este gargalo de negócios ao automatizar a extração de transcrições, aplicar processos de higienização semântica e gerar documentos Markdown hierarquizados.

O output final é uma base de conhecimento limpa e otimizada, pronta para:
* Alimentar ferramentas de IA generativa e assistentes virtuais (como o Google NotebookLM).
* Integrar arquiteturas RAG (Retrieval-Augmented Generation) locais ou em nuvem.
* Reduzir drasticamente os custos e o tempo operacional gastos com curadoria manual de conteúdo.

---

## 💎 Por que usar o Escriba?

*   **Estudo Sem Interrupções**: O Escriba cuida de toda a parte chata e técnica (como bloqueios e erros de login) para que você foque apenas no aprendizado.
*   **Economia de Tempo Real**: Ele mapeia canais inteiros em minutos e baixa apenas o que é novo, garantindo que sua biblioteca esteja sempre atualizada sem esforço.
*   **Conteúdo Pronto para Estudar**: Esqueça textos bagunçados. Você recebe documentos organizados por assunto, fáceis de ler e perfeitos para usar em ferramentas como o NotebookLM.
*   **Biblioteca de Conhecimento Offline**: Uma ferramenta essencial para pesquisadores e estudantes que precisam organizar grandes volumes de informação e ter tudo acessível para consulta rápida, mesmo sem internet.

---

## ⚡ Funcionalidades de Elite

*   **⚡️ Mapeamento JSON Híbrido**: Leitura ultrarrápida de conteúdo via YouTube-DLP com fallback inteligente e unificação de metadados por pasta.
*   **🛠️ Auto-Healing de Autenticação**: Detecta cookies inválidos, regenera o cache e continua o download sem interrupções.
*   **🧠 Motor de NLP Avançado**: Pipeline de 6 fases para limpeza de ruído, deduplicação de "muletas" orais e ancoragem temporal.
*   **📁 Repositório Único Inteligente**: Banco de dados JSON amarrado ao nome da pasta (`escriba_[folder_name].json`), com migração e consolidação automática de bases legadas.
*   **🎙️ Fallback de Áudio**: Se o vídeo não possui legendas, o Escriba extrai o áudio bruto (`.mp3`/`.m4a`) para processamento externo.

---

## 🏗️ Arquitetura do Sistema

O fluxo de processamento do Escriba transforma conteúdo audiovisual bruto em documentos semânticos estruturados:

```mermaid
graph LR
    A[YouTube / Video] --> B{Processamento}
    subgraph B [Escriba Pipeline]
        B1[Extração de Metadados]
        B2[Higienização via LLM/NLP]
        B3[Deduplicação de Roll-ups]
    end
    B --> C[Markdown Estruturado]
    C --> D[(Bases de Conhecimento / RAG)]
```

### 🧱 Modularidade (Developer-Friendly)
O núcleo foi refatorado para seguir padrões rigorosos de qualidade Python (PEP 8):
*   `youtube.py`: Abstração de rede e orquestração do `yt-dlp`.
*   `history.py`: Gestão de estado atômico e persistência JSON.
*   `rules.py`: Motor de limpeza léxica e processamento de regras.
*   `utils.py`: Sistema de design CLI e utilitários auxiliares.

---

## 🚀 Instalação

O Escriba é otimizado para **macOS**, mas roda perfeitamente em Linux, Windows e **Docker**.

### Opção 1: Via Docker (Recomendado)
A maneira mais rápida de rodar o Escriba com todas as dependências isoladas.

```bash
# 1. Build da Imagem
docker build -t escriba .

# 2. Execução (Monte o volume para preservar o cache e os arquivos)
docker run --rm -v "$(pwd):/app" escriba @CanalExemplo
```

### Opção 2: Configuração Local (Unix/macOS)

```bash
# 1. Clone e acesse o diretório
cd escriba

# 2. Prepare o ambiente (Criação única)
python3 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt

# 3. Use o script diretamente
python3 escriba.py @Canal
```

> [!TIP]
> **Auto-Venv**: O script possui lógica interna para se re-executar no ambiente virtual local se detectado!

### 🧪 Testes Unitários
Para garantir a integridade das regras de limpeza e do banco de dados:
```bash
# Executa todos os testes unitários
./.venv/bin/pytest tests/
```

---

## 🖋️ Customização de Termos (rules.txt)

O Escriba possui um motor de limpeza de termos dinâmico. Você pode personalizar como palavras específicas são tratadas criando um arquivo `rules.txt`:

1.  **Global**: `/Users/jandirp/scripts/escriba/rules.txt`
2.  **Local**: `./rules.txt` (regras específicas para a pasta/projeto atual).

**Formato do arquivo:**
```text
Termo Original, Termo Corrigido
PalavraAntiga = PalavraNova
Shabat, Shabbat
Ceu, Céu
```

---

## 🛠️ Como Operar

O Escriba aceita Handles (`@Canal`), URLs completas ou IDs de vídeos únicos.

```bash
# Sincronização Incremental (Padrão: mapeia canal, extrai subs e gera MD)
escriba @FilipeDeschamps

# Modo Áudio: Baixa MP3 de um vídeo específico
escriba -a https://youtu.be/dQw4w9WgXcQ

# Histórico Retroativo: Baixar apenas vídeos a partir de uma data
escriba -d 20260101 @CanalExemplo

# Manutenção: Regenerar todos os arquivos .md a partir do cache local
escriba --regen-md
```

### Flags de Poder
| Opção | Propósito |
|---|---|
| `-l, --lang` | Força o idioma (ex: `pt`, `en`). |
| `-a, --mp3` | Baixa o áudio convertido em MP3. |
| `-rc, --refresh-cookies` | Purga o cache de cookies e extrai novos do Chrome. |
| `-f, --fast` | **Modo Turbo**: Remove o delay entre requisições. |
| `--no-md` | Pula o motor de IA e preserva apenas o arquivo bruto. |

---

## 🧬 Escriba Scientific: O Motor de NLP

O Escriba implementa um pipeline proprietário de **Engenharia de Tópicos** para garantir que a transcrição seja legível por humanos e útil para LLMs.

### O Pipeline de Processamento
1.  **Janelas Adaptativas**: O tamanho da análise varia conforme a duração do vídeo.
2.  **Vetorização TF-IDF**: Cada janela é convertida em um vetor de importância léxica.
3.  **Cosine Similarity**: Detecta vales de similaridade para identificar quebras de tópico.
4.  **Deduplicação Dinâmica**: Remove o comportamento de "roll-up" das legendas automáticas.
5.  **Dicionário de Marcadores Orais**: Filtra ruídos como "né", "tipo", "basically".
6.  **Sanitização Estrutural**: Limpeza automática de artefatos HTML.

---

## 🏛️ Sobre o Escriba
Ferramenta desenvolvida para capacitar estudantes e profissionais a dominar grandes volumes de informação. O Escriba é o guardião da memória digital.

---

## Licença
[MIT](LICENSE) © 2026 Ekklezia.
