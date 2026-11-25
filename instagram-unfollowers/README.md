# Quem não me segue de volta no Instagram

Script em Python que compara quem você segue com quem te segue e devolve, em uma tabela, todos os perfis que **não te seguem de volta**.

```
Não te seguem de volta
+---+----------+------------------+------------------------------------+
| # | Usuário  | Você segue desde | Link                               |
+===+==========+==================+====================================+
| 1 | @loja.x  | 15/04/2022       | https://www.instagram.com/loja.x/  |
| 2 | @joao_99 | 14/11/2023       | https://www.instagram.com/joao_99/ |
+---+----------+------------------+------------------------------------+
```

A tabela aparece no terminal e também pode ser salva em **CSV**, **Excel (.xlsx)** ou em uma **página HTML** com busca.

## Instalação

Precisa do Python 3.9 ou mais novo.

```bash
cd instagram-unfollowers
pip install -r requirements.txt   # opcional: tabela colorida, Excel e modo login
```

## Modo 1: export oficial (recomendado)

Não pede senha e não tem risco de bloqueio.

1. No app do Instagram, vá em **Perfil → ☰ → Central de Contas → Suas informações e permissões → Baixar suas informações**.
2. Escolha **Algumas das suas informações → Seguidores e seguindo**.
3. Formato **JSON** (HTML também funciona), período **Desde o início**.
4. Quando o e-mail chegar, baixe o `.zip` e rode:

```bash
python unfollowers.py export instagram-seuusuario-2026-11-25.zip --html resultado.html
```

Pode passar o `.zip` direto ou a pasta já extraída. Nesse modo a tabela mostra também desde quando você segue cada perfil.

## Modo 2: login automático

Entra na sua conta com o [Instaloader](https://instaloader.github.io/) e baixa as listas na hora.

```bash
python unfollowers.py login seuusuario --xlsx resultado.xlsx
```

- A senha é digitada no terminal e **não é salva**. Depois do primeiro login o script guarda só a sessão, então as próximas execuções não pedem senha.
- Verificação em duas etapas é suportada.
- O Instagram limita esse tipo de acesso. Em contas com milhares de perfis ele pode pausar o download ou pedir confirmação no app. Use poucas vezes por dia e aumente `--delay` se der erro. Se travar, use o modo export.

## Opções

| Opção | O que faz |
|---|---|
| `--csv arquivo.csv` | Salva a tabela em CSV (abre direto no Excel) |
| `--xlsx arquivo.xlsx` | Salva em Excel, com filtro e links clicáveis |
| `--html arquivo.html` | Gera uma página com resumo, busca e links |
| `--ignore lista.txt` | Ignora perfis da lista, um por linha (ex.: famosos e marcas) |
| `--fans` | Também mostra quem te segue e você não segue de volta |
| `--no-table` | Não imprime a tabela no terminal |
| `--delay 5` | (login) Pausa em segundos a cada 50 perfis |

## Testes

```bash
python -m unittest test_unfollowers.py
```
