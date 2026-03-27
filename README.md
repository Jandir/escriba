<p align="center">
  <img src="logo.png" alt="Escriba Logo" width="220">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Versão-2.4.4-blue?style=for-the-badge" alt="Versão">
  <img src="https://img.shields.io/badge/Python-3.13+-ffd343?style=for-the-badge&logo=python&logoColor=black" alt="Python">
  <img src="https://img.shields.io/badge/Licença-MIT-green?style=for-the-badge" alt="Licença">
  <img src="https://img.shields.io/badge/Target-NotebookLM-6f42c1?style=for-the-badge&logo=google" alt="NotebookLM">
</p>

# Escriba
### O Orquestrador de Inteligência para YouTube

**Escriba** é um pipeline de engenharia de dados e NLP (Processamento de Linguagem Natural) de alta performance, projetado para converter canais inteiros do YouTube em bases de conhecimento locais, estruturadas e prontas para consumo por IAs como o **NotebookLM**.

Diferente de simples scripts de download, o Escriba atua como um **Escriba Digital**: ele não apenas "baixa" o conteúdo, ele o interpreta, deduplica roll-ups de legendas automáticas e segmenta semanticamente os tópicos para criar documentos `.md` de altíssima fidelidade.

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

## 🚀 Instalação

O Escriba é otimizado para **macOS**, mas roda perfeitamente em Linux e Windows.

### Configuração (Unix/macOS)

```bash
# 1. Clone e acesse o diretório
cd escriba

# 2. Prepare o ambiente (Criação única)
python3 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt

# 3. Use o script diretamente
# O Escriba agora detecta e usa o .venv automaticamente se estiver na pasta!
python3 escriba.py @Canal
```

> [!TIP]
> **Auto-Venv**: O script possui lógica interna para se re-executar no ambiente virtual local se detectado, garantindo que todas as dependências estejam sempre corretas sem que você precise ativar o ambiente manualmente.

---

## 🖋️ Customização de Termos (rules.txt)

O Escriba possui um motor de limpeza de termos dinâmico (padrão Ekklezia). Você pode personalizar como palavras específicas são tratadas criando um arquivo `rules.txt`:

1.  **Global**: `/Users/jandirp/scripts/escriba/rules.txt` (regras para todas as execuções).
2.  **Local**: `./rules.txt` (regras específicas para a pasta/projeto atual).

**Formato do arquivo:**
```text
# Comentários são permitidos
Termo Original, Termo Corrigido
PalavraAntiga = PalavraNova
Shabat, Shabbat
Ceu, Céu
```
As regras locais têm precedência sobre as globais.

---

### Configuração (Windows)

```powershell
# 1. Clone e acesse o diretório
cd escriba

# 2. Crie e prepare o ambiente virtual
python -m venv .venv
.\.venv\Scripts\activate
pip install yt-dlp python-dotenv scikit-learn nltk numpy pysrt

# 3. Crie o comando global (Opcional - PowerShell)
# Execute para adicionar o alias ao seu perfil do PowerShell
$EscribaDir = Get-Location
Add-Content -Path $PROFILE -Value "function escriba { & '$EscribaDir\.venv\Scripts\python.exe' '$EscribaDir\escriba.py' `$args }"
```

---

## 🛠️ Como Operar

O Escriba aceita Handles (`@Canal`), URLs completas ou IDs de vídeos únicos.

```bash
# Sincronização Incremental (Padrão: mapeia canal, extrai subs e gera MD)
escriba @FilipeDeschamps

# Modo Cirúrgico: Apenas áudio de um vídeo específico
escriba -a https://youtu.be/dQw4w9WgXcQ

# Histórico Retroativo: Baixar apenas vídeos a partir de uma data
escriba -d 20260101 @CanalExemplo

# Manutenção: Regenerar todos os arquivos .md a partir do cache local
escriba --regen-md
```

### Flags de Poder
| Opção | Propósito |
|---|---|
| `-l, --lang` | Força o idioma (ex: `pt`, `en`) caso haja alguma falha na detecção automática. |
| `--audio-fallback`| Baixa o áudio caso não existam legendas disponíveis. |
| `-rc, --refresh` | Purga o cache de cookies e extrai novos do Chrome. |
| `-f, --fast` | **Modo Turbo**: Remove o delay entre requisições. O delay foi implementado para evitar bloqueios do YouTube. |
| `--no-md` | Pula o motor de IA e preserva apenas o arquivo bruto. |

---

## 🧬 Escriba Scientific: O Motor de NLP

O Escriba implementa um pipeline proprietário de **Engenharia de Tópicos** para garantir que a transcrição seja legível por humanos e útil para LLMs.

### O Pipeline de Processamento
1.  **Janelas Adaptativas**: O tamanho da análise varia conforme a duração do vídeo (30s a 90s).
2.  **Vetorização TF-IDF**: Cada janela é convertida em um vetor de importância léxica.
3.  **Cosine Similarity**: Detecta vales de similaridade entre janelas para identificar quebras de tópico.
4.  **Deduplicação Dinâmica**: Remove o comportamento de "roll-up" (repetição de linhas) das legendas automáticas.
5.  **Dicionário de Marcadores Orais**: Filtra ruídos como "né", "tipo", "basically" que poluem a semântica.
6.  **Sanitização Estrutural**: Limpeza automática de artefatos HTML e formatações indesejadas na geração dos arquivos finais.

---

## 🏛️ Sobre o Escriba
Ferramenta desenvolvida para capacitar estudantes e profissionais a dominar grandes volumes de informação. O Escriba é o guardião da memória digital, garantindo que nenhum insight se perca na imensidão do algoritmo do YouTube.

---

## Licença
[MIT](LICENSE) © 2026 Ekklezia.
