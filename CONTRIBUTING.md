# Como contribuir com a A.U.R.A.

Obrigado pelo interesse! A A.U.R.A. é um projeto pessoal e aberto: sugestões, correções e ideias são bem-vindas.
Tudo passa por revisão antes de entrar: ninguém mexe direto no projeto.

## Antes de mexer no código: abra uma Issue

Para **relatar um erro** ou **sugerir uma ideia**, abra uma [Issue](https://github.com/wesleym12/aura/issues) contando:

- **O que aconteceu** e **o que você esperava**.
- **Como reproduzir**: o que você pediu (texto ou voz), em qual modo (janela, entalhe, navegador, celular).
- **Onde roda**: Windows ou Linux, motor (Próprio ou Gemini Live) e modelo.
- O trecho do erro, se houver (`docker compose logs aura --tail 50`, sem chaves nem dados pessoais).

Para mudanças grandes (habilidade nova, tela nova), combine na Issue antes de programar: assim ninguém perde tempo.

## Enviando uma mudança (Pull Request)

1. Faça um **fork** do projeto e crie uma branch a partir da `main` (ex.: `corrige-timer`).
2. Faça a mudança, **pequena e focada** em um assunto só.
3. **Teste** (veja abaixo) e conte no Pull Request **o que você testou e como**.
4. Abra o **Pull Request** para a `main`, ligado à Issue (ex.: "Resolve #12").

O dono do projeto revisa, pode pedir ajustes e decide se a mudança entra.

## Jeito do projeto

- **Português do Brasil** em tudo que a pessoa vê: telas, mensagens, documentação e mensagens de commit.
- **Privacidade primeiro**: nada sai do computador sem a pessoa ligar ou pedir. Serviço novo de terceiros entra em
  [`PRIVACIDADE.md`](PRIVACIDADE.md) e, se tiver licença ou termos próprios, em [`NOTICE.md`](NOTICE.md).
- **Ações que mudam algo** (apagar, enviar, clicar, desligar…) pedem **Autorizar** ou têm **Desfazer**.
- **Sem segredos no código**: chaves, tokens e senhas ficam no banco local ou no `.env` (que não vai para o Git).
- **Windows e Linux**: o que só funciona em um dos dois precisa falhar com uma mensagem clara no outro.
- Os scripts do Windows (`.ps1`) usam **só caracteres ASCII** (o PowerShell 5.1 lê acentos errado).

## Testes

Com a A.U.R.A. rodando (`docker compose up -d`):

```bash
python tests/test_host_contract.py                                   # servidor x agente do Windows
docker compose exec -T aura python - < tests/test_tools_host.py      # ferramentas de controle do PC
docker compose exec -T aura python - < tests/test_tool_choice.py     # o modelo local escolhe a ferramenta certa
```

Mudou a tela? Teste nos dois modos (janela e entalhe) e, se puder, no tema claro e no escuro.

## Licença

Ao enviar uma contribuição, você concorda que ela seja distribuída sob a mesma licença do projeto,
a [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-or-later).
