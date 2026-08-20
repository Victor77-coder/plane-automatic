# plane-automatic

CLI para abrir demandas no Plane. Os três comandos são independentes: o Intake **não** é o caminho do time de suporte.

- **Desenvolvedor, sem demanda de suporte** → `intake create` (fila de Intake; o suporte aprova no Plane). Mesmo template e mesma IA do `suporte create`. Já nasce com a label `aguardando interno`.
- **Time de suporte** → `suporte create` (work item no board SUPORTE, template preenchido pela IA). Não passa pelo Intake.
- **Desenvolvedor, demanda de suporte já existe** → `tecnica create --from SUP-453` (board do produto, relação `implements`, sub-item de trabalho).

O time de suporte usa o **terminal do sistema** (Terminal no macOS, Prompt/PowerShell no Windows). Não precisa de IDE.

Licença: [MIT](LICENSE).

## Privacidade (LLM / LGPD)

`intake create`, `suporte create` e `tecnica create` enviam o relato (e os fatos extraídos da demanda) para o provedor configurado (**Groq** ou **OpenAI**). Isso pode incluir dados pessoais de cliente. Use uma chave da sua organização e siga a política interna (LGPD). Se o texto não puder sair da empresa, aponte `OPENAI_BASE_URL` para um endpoint interno compatível com a API OpenAI, ou não use estes comandos. Sem chave de LLM, eles falham — o CLI **não** cola o texto cru no Plane.

## Pré-requisitos

- Python 3.10+
- Conta na instância Plane e permissão nos projetos
- Personal Access Token
- `GROQ_API_KEY` ou `OPENAI_API_KEY`

### Gerar o token

1. Entre na sua instância Plane
2. **Profile Settings** → **Personal Access Tokens**
3. Crie um token e copie o valor (`plane_api_...`)

## Instalação (uma vez)

### Windows (PowerShell) — time de suporte

O suporte **não** precisa de `projects.yaml`. Só o `.env` (token do Plane, URL da instância, slug, UUID do projeto SUPORTE e chave de LLM).

1. Instale o Python 3.12 em [python.org/downloads](https://www.python.org/downloads/). No instalador, marque **Add python.exe to PATH**. Não use a Microsoft Store.
2. Feche o PowerShell e abra de novo.
3. Confira: `python --version` deve mostrar `Python 3.12...` (não a mensagem da Store).
4. Vá até a pasta do projeto (a que contém `plane_cli` e `pyproject.toml`) e rode:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
Copy-Item .env.example .env
```

Se o `Activate.ps1` for bloqueado, rode uma vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

O prompt deve ficar `(.venv) PS C:\...\plane-automatic>`. Depois dá para usar `plane-cli` ou `python -m plane_cli`.

### macOS / Linux

```bash
cd plane-automatic
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
cp .env.example .env
```

Quem for usar `tecnica create` também copia o mapa de projetos:

```bash
cp projects.yaml.example projects.yaml
```

Edite o `.env`:

```bash
PLANE_API_KEY=plane_api_...
PLANE_BASE_URL=https://sua-instancia.example
PLANE_WORKSPACE_SLUG=seu-workspace
PLANE_SUPPORT_PROJECT_ID=uuid-do-projeto-de-suporte
PLANE_LLM_PROVIDER=groq
GROQ_API_KEY=
# ou OPENAI_API_KEY= se preferir OpenAI
```

O slug aparece na URL: `https://<instancia>/<slug>/projects/`.

```bash
python -m plane_cli projects
python -m plane_cli labels
```

`projects.yaml` é **só para `tecnica create`**: mapeia a **label** da demanda de suporte (case-insensitive) para o UUID do board técnico.

```yaml
produto:exemplo: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

As chaves precisam coincidir com as labels do projeto de suporte. `python -m plane_cli labels` lista os nomes exatos.

### Uso no dia a dia

Windows (PowerShell), na pasta do projeto:

```powershell
.\.venv\Scripts\Activate.ps1
plane-cli suporte create --help
```

macOS / Linux:

```bash
source .venv/bin/activate
plane-cli suporte create --help
```

`--dry-run` redige o template e **não** cria o item no Plane. A saída dos `create` é JSON no stdout (id, sequence, url). Erros e avisos vão para stderr.

## Helpers

```bash
python -m plane_cli projects
python -m plane_cli labels
python -m plane_cli labels --project-id <uuid>
python -m plane_cli states
python -m plane_cli states --project-id <uuid>
```

## Desenvolvedor — Intake

Quando **não há** demanda de suporte. Abre na fila de Intake para o suporte aprovar no Plane. A IA redige o **mesmo template** do `suporte create`; o texto cru **não é colado**.

```bash
python -m plane_cli intake create \
  --description "Cliente não consegue aplicar preços de cotação parcial" \
  --label produto:cotacoesgov \
  --priority high
```

O CLI aplica a label `aguardando interno` e atribui o responsável ao usuário do token. `--dry-run` mostra o HTML sem criar o Intake.

## Time de suporte — board SUPORTE

Cria o work item **já no board**. Não passa pelo Intake.

```bash
python -m plane_cli suporte create \
  --description "Cliente não consegue aplicar preços de cotação parcial" \
  --label produto:cotacoesgov \
  --priority high
```

`--description` ou `--description-file` é obrigatório. `--title` é opcional. Sem chave de LLM, o comando falha.

Overrides depois da IA: `--necessidade`, `--cenario`, `--resultado`, `--solicitante-nome`, `--organizacao`, `--canal`.

## Desenvolvedor — demanda técnica

Quando a demanda de suporte **já existe**.

```bash
python -m plane_cli tecnica create --from SUPORTE-123 \
  --trabalho "Corrigir timeout no service_cpe e documentar o fallback"
```

`--from` aceita a chave (`SUPORTE-123` ou `SUP-123`) ou o UUID. O prefixo precisa bater com o identifier do projeto de suporte (FOO-123 é rejeitado).

Se o sub-item falhar, a demanda técnica permanece; o CLI imprime a URL e o erro.

```bash
python -m plane_cli tecnica create --from SUPORTE-123 --dry-run
```

## Estrutura

```
plane-automatic/
  .env.example
  projects.yaml.example
  pyproject.toml
  plane_cli/
  tests/
```
