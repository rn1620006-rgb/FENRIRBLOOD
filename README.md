# FENRIRBLOOD — MYTHIC WOLF 🐺
**A MATILHA NÃO SE CURVA.**

Plataforma web original para a gestão de guilda **Free Fire — Servidor Europa**, em **português de Portugal**. Código-fonte próprio e independente. Não se liga à aplicação, repositório, credenciais ou Firebase do projeto Os Pinguins.

## Estado da entrega

**Versão entregue: Fase 1–4 parcial, base funcional testada.** Esta versão não é uma implementação completa de todo o master brief. O objetivo aqui foi entregar um sistema verdadeiro e executável, sem mockups ligados a números fictícios e sem ferramentas que gastem créditos. **Não há aplicação publicada na internet** e esta entrega não equivale a uma auditoria de segurança ou certificação de produção.

### Implementado e funcional na API / interface

| Domínio | Funcionalidade | Estado |
|---|---|---|
| Identidade | Página de entrada, login, registo e candidatura pendente | Implementado |
| Segurança | Argon2id, sessão com token aleatório guardado por hash, cookie HttpOnly, CSRF, SameSite, bloqueio de tentativas, logout/logout de todas as sessões | Implementado |
| Governança | Dois fundadores independentes, iniciais por CLI seguro; cargos, aprovação de membros e permissão por endpoint | Implementado |
| Aprovação dupla | Propor, assinar por duas identidades, execução transacional, bloqueio de aprovação duplicada | Implementado |
| Diretório | Perfis, pesquisa local, privacidade básica, informação e presença recente | Implementado |
| Esquadrões | 4 jogadores por equipa com concorrência controlada por transação; capitães; transferências; reserva; adaptação 14+7 dias | Implementado |
| Guerras | Agendamento, convocatórias, confirmação e lançamento manual de resultados | Implementado |
| Ranking | Pontuações por semana em Europe/Lisbon, correções justificadas, histórico persistente e validação final dupla | Implementado |
| Feed | Publicações, até 4 imagens WebP verificadas por publicação, comentários, reações, moderação e paginação | Implementado |
| Mensagens | Canais geral, administrativo, por equipa, guerra e privadas com isolamento de participantes; atualização periódica | Implementado com *polling*, não WebSockets |
| Eventos | Agenda e criação por cargos autorizados | Implementado |
| Hall | Conquistas reais atribuídas pela administração | Implementado |
| Inteligência | Indicadores verificáveis (inatividade, equipas incompletas, reserva, candidaturas); sem IA simulada | Implementado sem modelos externos |
| Moderação | Advertências, suspensão e reintegração mediante votação dupla, recurso do jogador, auditoria | Implementado |
| Notificações | Avisos persistentes e lidos/não lidos | Implementado com *polling* |
| Responsividade | CSS móvel/desktop, safe area, 16px nos formulários iOS, acessibilidade básica e movimento reduzido | Criado, sem teste gráfico completo em Safari real |

### Explicitamente não implementado / ainda dependente

- Auditoria técnica do **ZIP completo de Os Pinguins**: o ZIP não estava disponível nesta execução, portanto não foi extraído nem inspecionado; o trabalho é uma base original.
- Integração GLB/3D oficial de Fenrir, animação de entrada em vídeo e emblema definitivo; usa apenas **FB tipográfico**. Nenhum asset 3D falso foi criado.
- Integração de modelos de IA reais (não há simulação).
- WebSockets, indicador de leitura/entrega e notificações push no sistema de mensagens; o sistema usa polling autenticado.
- Relatórios automáticos da semana ao meio-dia, congelamento automático às 18h e fecho automático às 23h59. O ciclo temporal é documentado; a validação manual dupla existe.
- Verificação obrigatória de email (registo é pendente e aprovado por administrador). Recuperação de password por email **somente após configurar SMTP**.
- Carrosséis avançados, galerias de vários posts, editor de cenas, efeitos 3D, personalização global de temas e cosméticos.
- Testes cross-browser completos (Safari iOS, Android Chrome) e uma revisão abrangente de segurança/pentest.
- Plano de backup automatizado, PostgreSQL, armazenamento de objetos S3 e infraestrutura de produção escalável.
- Publicação no GitHub, no Replit, Render ou noutro serviço. Esta entrega é um projeto ZIP portátil.

## Instalação local

Necessário: Python **3.11 ou superior**. Não exige Node, npm, Replit, Floot, Firebase, API paga ou chaves cloud.

```bash
unzip FENRIRBLOOD-codigo-fonte.zip
cd fenrirblood
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edite `.env` se necessário. Em ambiente local: `FENRIR_SECURE_COOKIES=false`, `FENRIR_PUBLIC_URL=http://localhost:8000`. Em produção HTTPS: `FENRIR_SECURE_COOKIES=true` e a URL pública correta, com `FENRIR_ALLOWED_ORIGINS` no domínio correto.

**Configurar os dois fundadores** — na primeira execução apenas, numa consola privada:

```bash
python scripts/bootstrap_founders.py
```

Indica o email, nome e uma palavra-passe distinta de pelo menos 12 caracteres para cada fundador. A operação é atómica e não pode ser repetida após qualquer fundador ser criado. **Não há fundadores de demonstração nem passwords predefinidas no ZIP.**

**Iniciar servidor:**

```bash
python run.py
```

Abre **http://localhost:8000**. Os novos utilizadores criam uma conta, ficam pendentes e um fundador ou administrador de membros aprova a candidatura.

### Testes

```bash
python -m pytest -q
```

Os testes usam bases SQLite temporárias criadas pelo pytest; não alteram a base normal do teu projeto. Os ficheiros `.spec`/`tests` estão incluídos no ZIP.

## Segurança e desenho técnico

- Backend **FastAPI / Python**, com HTML/CSS/JavaScript modular. Esta escolha é intencional: permite criar, executar e testar tudo localmente sem npm/serviço externo. Não é React/Vite; uma evolução futura pode substituir apenas o frontend mantendo a API. A stack foi adaptada à restrição de não usar créditos e de manter uma aplicação executável, em vez de entregar React que não foi compilado.
- Base de dados **SQLite** isolada em `data/fenrirblood.sqlite3`, com WAL, foreign keys e migrações em `migrations/`. Restrições de unicidade e `BEGIN IMMEDIATE` para evitar equipas com mais de quatro jogadores e votos simultâneos duplicados. Para produção multi-instância, migrar para PostgreSQL.
- Hash Argon2 de palavras-passe, tokens de sessão aleatórios guardados apenas como SHA-256 na base, cookie `HttpOnly`, `SameSite=Lax` e `Secure` configurável (obrigatório em HTTPS).
- Todos os endpoints protegidos verificam autorização no servidor; as mutações com sessão usam `X-CSRF-Token`. O HTML aplica escape a conteúdo fornecido por membros.
- Imagens são verificadas com Pillow, limitadas por formato, tamanho e resolução, regravadas em WebP sem EXIF e servidas apenas após autenticação. Armazenamento local requer volume persistente em produção.
- Toda a votação estratégica necessita de **dois fundadores distintos**, com assinatura do proponente como primeira aprovação e segundo fundador como executor. Não é possível autoaprovar duas vezes.
- Contas suspensas podem voltar a autenticar-se exclusivamente para consultar o estado e apresentar recurso; não acedem aos módulos internos.
- Perfis privados são ocultados do diretório para membros comuns; mensagens privadas só podem ser lidas por remetente/destinatário.
- `audit_log` grava ações sensíveis, mas não é uma solução imutável externa. Protege/backupa o ficheiro da base e restringe acesso de sistema operativo.

## Estrutura

```text
fenrirblood/
├── app/
│   ├── main.py                  # FastAPI, CSP e headers de segurança
│   ├── auth_routes.py           # Contas, sessões e passwords
│   ├── guild_routes.py          # Dashboard, membros, equipas, guerras, ranking, eventos
│   ├── social_routes.py         # Feed, reações, comentários, mensagens, notificações
│   ├── admin_routes.py          # Admissões, auditoria, disciplina e dupla aprovação
│   ├── media_routes.py          # Upload seguro de imagens
│   ├── insights_routes.py       # Hall e inteligência baseada em dados
│   ├── db.py                    # SQLite e migrações
│   ├── security.py              # Argon2, tokens e fuso horário
│   └── config.py
├── templates/index.html        # Interface base
├── static/app.js               # Frontend interativo
├── static/styles.css           # Design premium responsive
├── migrations/                 # Migrações SQL versionadas
├── scripts/bootstrap_founders.py
├── tests/test_api.py
├── run.py
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Deploy e dados

Para testar localmente, o arranque acima é suficiente. Para colocares a aplicação online:

1. Cria um repositório Git **novo**; não uses os repositórios Os Pinguins/LEVIATHAN/Jarvis.
2. Configura um serviço Python/Docker com HTTPS e um volume persistente para `/app/data`. **Não guardes uma base SQLite num filesystem efémero.**
3. Define `FENRIR_DB_PATH=/app/data/fenrirblood.sqlite3`, `FENRIR_SECURE_COOKIES=true`, `FENRIR_PUBLIC_URL` e `FENRIR_ALLOWED_ORIGINS` para o domínio de produção.
4. Executa o bootstrap dos dois fundadores apenas uma vez, a partir de um ambiente privado e seguro.
5. Configura SMTP se precisares da recuperação por email.
6. Antes de receber membros reais, implementa políticas de retenção, consentimento, backups automáticos cifrados e testes de restauração.
7. Para maior escala, substitui SQLite por PostgreSQL, armazenamento local por object storage privado e polling por canais tempo real robustos.

O Dockerfile serve a API HTTP na porta indicada por `PORT` (8000 por omissão). Usa sempre proxy HTTPS externo. Não há código malicioso, credenciais originais, dados de jogadores nem chaves no pacote.

## Operação / regras

- **Dois fundadores**: acesso equivalente. Promoções e suspensões estratégicas por aprovação dupla; fundadores não podem ser removidos por ação normal.
- **Admin. Membros**: pode aprovar candidaturas, aplicar advertências, moderar o feed e aceder a relatórios de auditoria.
- **Admin. Operacional**: cria equipas, gere guerras, ranking e convocações.
- **Capitão**: pode gerir jogadores apenas do seu esquadrão.
- **Membro**: perfil, publicação, chat, consulta e confirmação da sua convocatória.
- **Pendente**: sem acesso aos módulos até aprovação.
- **Ranking**: fuso `Europe/Lisbon`, semanas a começar à segunda-feira; registos justificáveis; validação final mediante dois fundadores bloqueia alterações futuras à semana.
- **Disciplina**: duas advertências ou exceção de infração grave justificada antes de suspensão proposta por fundador; segundo fundador valida; possibilidade de recurso.

### Auditoria de funcionalidades

Não confundir `funcional na API e testada` com `concluída para produção`: o domínio 3D, IA opcional, conectores Free Fire inexistentes, chats WebSocket, publicação e deploy permanecem por concluir. A aplicação não reivindica acesso à API oficial de Free Fire.

**FENRIRBLOOD — A MATILHA NÃO SE CURVA.**


## Aviso: Vercel — pré-visualização, NÃO produção

Quando esta versão é publicada no Vercel, a interface FastAPI fica disponível, mas todas as operações de escrita são deliberadamente desativadas (HTTP 503) porque a base de dados SQLite usa o armazenamento efémero das Functions. Isto evita perder contas, sessões, mensagens e ações de administração sem aviso. O sistema **não está pronto para receber membros reais nesta instalação**. Para produção, migrar a camada de persistência para PostgreSQL gerido e usar armazenamento de objetos para os uploads; depois fazer testes de regressão e só então ativar os endpoints de escrita. Para utilização operacional hoje, executar com Python/Docker num servidor com disco persistente e HTTPS.

Ficheiro de entrada para o Vercel: app.py na raiz; vercel.json ativa deteção FastAPI. O ZIP original mantém-se preservado como backup no repositório.
