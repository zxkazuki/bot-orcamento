# Leograf Orçamentos

Bot Telegram de triagem de orçamentos gráficos para a empresa Leograf.

Vendedores enviam pedidos de orçamento via Telegram. O bot usa IA (Claude via AWS Bedrock + Knowledge Base) para validar se o pedido contém os 7 campos obrigatórios: Produto, Quantidade, Formato, Papel, Gramatura, Cores e Acabamento.

- Pedido incompleto → bot pede os campos faltantes ao vendedor
- Pedido completo → bot confirma ao vendedor e encaminha o resumo ao orçamentista via outro bot Telegram

O sistema opera com dois bots Telegram: um para vendedores e outro para o orçamentista.

Versão atual: 0.5.0

Idioma do produto: Português (Brasil). Todas as mensagens ao usuário e prompts de sistema são em PT-BR.
