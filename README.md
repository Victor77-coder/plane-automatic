# plane-automatic

CLI para abrir **Intake** no projeto de suporte e **demanda técnica** no board do sistema correspondente, no Plane self-hosted (`https://plane.promaxima.cloud/`).

Replica o processo do time:

1. Se **não existe** demanda de suporte → cria um Intake (a aprovação continua manual no Plane).
2. Se **já existe** demanda de suporte → lê a label do sistema, cria o work item no projeto técnico, liga os dois com `relates_to` e cria um **sub-item de trabalho**.

## Pré-requisitos

- Python 3.10+
- Conta na instância Plane e permissão nos projetos
- Personal Access Token
- Chave de LLM (`GROQ_API_KEY` ou `OPENAI_API_KEY`) para redigir a demanda técnica

### Gerar o token

1. Entre em [plane.promaxima.cloud](https://plane.promaxima.cloud/)
2. **Profile Settings** → **Personal Access Tokens**
3. Crie um token e copie o valor (`plane_api_...`)

## Instalação

```bash
cd plane-automatic
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp projects.yaml.example projects.yaml
```

Edite o `.env`:

```bash
PLANE_API_KEY=plane_api_...
PLANE_BASE_URL=https://plane.promaxima.cloud
PLANE_WORKSPACE_SLUG=seu-workspace
PLANE_SUPPORT_PROJECT_ID=uuid-do-projeto-de-suporte
PLANE_LLM_PROVIDER=groq
GROQ_API_KEY=
# ou OPENAI_API_KEY= se preferir OpenAI
```

O slug aparece na URL: `https://plane.promaxima.cloud/<slug>/projects/`.

Descubra o UUID do projeto de suporte e dos projetos técnicos:

```bash
python -m plane_cli projects
python -m plane_cli labels
```

Preencha `projects.yaml` com o **nome da label** da demanda de suporte (case-insensitive) apontando para o UUID do board técnico:

```yaml
produto:fontedeprecos: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
produto:cotacoesgov: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
produto:controlegov: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

As chaves precisam coincidir com as labels usadas no projeto de suporte. `python -m plane_cli labels` lista os nomes exatos.

## Comandos

### Helpers

```bash
python -m plane_cli projects
python -m plane_cli labels
python -m plane_cli labels --project-id <uuid>
python -m plane_cli states
python -m plane_cli states --project-id <uuid>
```

### Fluxo 1 — sem demanda de suporte (Intake)

```bash
python -m plane_cli intake create \
  --title "Erro ao gerar PDF" \
  --description "Cliente X, ambiente prod" \
  --priority high
```

Cria o Intake no projeto de suporte **já com o template da demanda de suporte** (Solicitante, Necessidade, Cenário atual, Resultado esperado, Impacto, Evidências, Contexto, Atendimento). `--description` preenche a seção **Necessidade**; a data da solicitação entra como hoje. A aprovação continua manual no Plane. **Não** cria sub-item de trabalho.

### Fluxo 2 — demanda de suporte já existe (técnica + trabalho)

```bash
python -m plane_cli tecnica create --from SUPORTE-123 \
  --trabalho "Corrigir timeout no service_cpe e documentar o fallback"
```

`--from` aceita a chave (`SUPORTE-123`) ou o UUID da demanda de suporte.

O CLI:

1. Busca a demanda no projeto de suporte
2. Resolve o projeto técnico pela label `produto:...` (ou por `--project-id`)
3. Extrai os **fatos** da demanda de suporte e pede a um LLM para **redigir** a demanda técnica (título, problema, solução, escopo, critérios, riscos, validação). O texto **não é copiado** do suporte. O título técnico é baseado no do suporte, sem `[CLIENTE]`.
4. Atribui o **responsável** à mesma pessoa do **criado por** (usuário do token) e preenche Validação → Responsável
5. Preenche **Demanda de origem** com a chave/URL do suporte e **Relação: implements**
6. Tenta a relação nativa `implements`; se a API não aceitar, cai para `relates_to` e, por último, um link
7. Pede à IA um **sub-item Trabalho** a partir da demanda técnica (não copia o texto): título de implementação, Objetivo, lista de tarefas, critérios de conclusão, evidências em branco e planejamento (responsável = criado por)

`--title` e `--trabalho-title` sobrescrevem os títulos gerados. `--description` e `--solucao` sobrescrevem **depois** da IA as seções Problema técnico e Solução proposta. `--trabalho` é orientação extra para a IA do sub-item, não o corpo final. Sem `GROQ_API_KEY` nem `OPENAI_API_KEY`, o comando falha (não cola o texto do suporte).

Se o sub-item falhar, a demanda técnica permanece; o CLI imprime a URL e o erro.

Overrides:

```bash
python -m plane_cli tecnica create --from SUPORTE-123 \
  --project-id <uuid-do-projeto-tecnico> \
  --title "Timeout no CPE" \
  --description-file ./problema.md \
  --solucao-file ./solucao.md \
  --priority high \
  --trabalho-file ./escopo.md \
  --trabalho-title "Trabalho"
```

Se várias labels da demanda mapearem para projetos diferentes, o comando falha e pede `--project-id`. Se nenhuma label bater com `projects.yaml`, lista as labels encontradas.

A saída de `intake create` e `tecnica create` é JSON no stdout (id, sequence, url). Erros vão para stderr.

## Estrutura

```
plane-automatic/
  .env.example
  projects.yaml.example
  plane_cli/
    cli.py
    client.py
    config.py
    mapping.py
    html.py
    llm.py
    templates.py
```
