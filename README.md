# plane-automatic

CLI para abrir demandas no Plane (`https://plane.promaxima.cloud/`). Os três comandos são independentes: o Intake **não** é o caminho do time de suporte.

- **Desenvolvedor, sem demanda de suporte** → `intake create` (fila de Intake; o suporte aprova no Plane). Mesmo template e mesma IA do `suporte create`. Já nasce com a label `aguardando interno`.
- **Time de suporte** → `suporte create` (work item no board SUPORTE, template preenchido pela IA). Não passa pelo Intake.
- **Desenvolvedor, demanda de suporte já existe** → `tecnica create --from SUP-453` (board do produto, relação `implements`, sub-item de trabalho).

O time de suporte usa o **terminal do sistema** (Terminal no macOS, Prompt/PowerShell no Windows). Não precisa de IDE.

## Pré-requisitos

- Python 3.10+
- Conta na instância Plane e permissão nos projetos
- Personal Access Token
- `GROQ_API_KEY` ou `OPENAI_API_KEY` para `intake create`, `suporte create` e `tecnica create`

### Gerar o token

1. Entre em [plane.promaxima.cloud](https://plane.promaxima.cloud/)
2. **Profile Settings** → **Personal Access Tokens**
3. Crie um token e copie o valor (`plane_api_...`)

## Instalação (uma vez)

No terminal, na pasta do projeto:

```bash
cd plane-automatic
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp projects.yaml.example projects.yaml
```

No Windows, ative o ambiente com `.venv\Scripts\activate`.

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

```bash
python -m plane_cli projects
python -m plane_cli labels
```

`projects.yaml` é só para `tecnica create`: mapeia a **label** da demanda de suporte (case-insensitive) para o UUID do board técnico.

```yaml
produto:fontedeprecos: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
produto:cotacoesgov: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
produto:controlegov: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

As chaves precisam coincidir com as labels do projeto de suporte. `python -m plane_cli labels` lista os nomes exatos.

### Uso no dia a dia

```bash
cd plane-automatic
source .venv/bin/activate
```

A saída dos `create` é JSON no stdout (id, sequence, url). Erros e avisos vão para stderr.

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

O CLI:

1. Pede à IA o título e as seções (Solicitante, Necessidade, Cenário atual, Resultado esperado, Impacto, Contexto, Atendimento)
2. Preenche a **data da solicitação** com o dia de hoje
3. Deixa **Evidências** em branco, salvo se o relato trouxer o fato
4. Aplica a label `aguardando interno` sozinha
5. Aplica `--label` extra (repetível; aceita o nome, ex. `produto:cotacoesgov`)

`--description` ou `--description-file` é obrigatório. `--title` é opcional; se omitir, a IA redige o título (sem `[CLIENTE]`). Sem chave de LLM, o comando falha.

Se a label `aguardando interno` não existir no projeto SUPORTE, o CLI avisa e cria o Intake mesmo assim. Se não houver `produto:...`, avisa (a demanda técnica depois depende disso) mas não bloqueia.

Overrides depois da IA (iguais ao `suporte create`): `--necessidade`, `--cenario`, `--resultado`, `--solicitante-nome`, `--organizacao`, `--canal`.

## Time de suporte — board SUPORTE

Cria o work item **já no board**. Não passa pelo Intake. Usa o mesmo template e a mesma IA do `intake create`; o texto cru **não é colado**.

```bash
python -m plane_cli suporte create \
  --description "Cliente não consegue aplicar preços de cotação parcial" \
  --label produto:cotacoesgov \
  --priority high
```

O CLI:

1. Pede à IA o título e as seções (Solicitante, Necessidade, Cenário atual, Resultado esperado, Impacto, Contexto, Atendimento)
2. Preenche a **data da solicitação** com o dia de hoje
3. Deixa **Evidências** em branco, salvo se o relato trouxer o fato (link, log, etc.)
4. Atribui o **responsável** à pessoa do token (criado por)
5. Aplica as labels (`--label` repetível; aceita o nome, ex. `produto:cotacoesgov`)

`--description` ou `--description-file` é obrigatório. `--title` é opcional; se omitir, a IA redige o título (sem `[CLIENTE]`). Sem chave de LLM, o comando falha.

Se não houver label `produto:...`, o CLI avisa (a demanda técnica depois depende disso) mas não bloqueia.

Overrides depois da IA (só se você passar a flag):

```bash
python -m plane_cli suporte create \
  --description-file ./relato.txt \
  --title "Aplicar preços de cotação parcial" \
  --label produto:cotacoesgov \
  --necessidade "Permitir aplicar preços mesmo com cotação parcial" \
  --cenario "Hoje a tela bloqueia quando falta item" \
  --resultado "Aplicar os itens já cotados e seguir o restante depois" \
  --solicitante-nome "Maria" \
  --organizacao "Cliente X" \
  --canal "e-mail" \
  --priority high
```

## Desenvolvedor — demanda técnica

Quando a demanda de suporte **já existe**.

```bash
python -m plane_cli tecnica create --from SUPORTE-123 \
  --trabalho "Corrigir timeout no service_cpe e documentar o fallback"
```

`--from` aceita a chave (`SUPORTE-123`) ou o UUID.

O CLI:

1. Busca a demanda no projeto de suporte
2. Resolve o projeto técnico pela label `produto:...` (ou por `--project-id`)
3. Extrai os **fatos** da demanda de suporte e pede a um LLM para **redigir** a demanda técnica (título, problema, solução, escopo, critérios, riscos, validação). O texto **não é copiado** do suporte. O título técnico é baseado no do suporte, sem `[CLIENTE]`.
4. Atribui o **responsável** à mesma pessoa do **criado por** (usuário do token) e preenche Validação → Responsável
5. Preenche **Demanda de origem** com a chave/URL do suporte e **Relação: implements**
6. Tenta a relação nativa `implements`; se a API não aceitar, cai para `relates_to` e, por último, um link
7. Pede à IA um **sub-item Trabalho** a partir da demanda técnica (não copia o texto): título de implementação, Objetivo, lista de tarefas, critérios de conclusão, evidências em branco e planejamento (responsável = criado por)

`--title` e `--trabalho-title` sobrescrevem os títulos gerados. `--description` e `--solucao` sobrescrevem **depois** da IA as seções Problema técnico e Solução proposta. `--trabalho` é orientação extra para a IA do sub-item, não o corpo final. Sem chave de LLM, o comando falha.

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
