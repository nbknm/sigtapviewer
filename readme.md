# Sigtap Viewer

O **SIGTAP Viewer** é uma ferramenta desktop desenvolvida em Python para profissionais de faturamento hospitalar, gestores de saúde e desenvolvedores que precisam consultar a Tabela Unificada de Procedimentos, Medicamentos, Órteses, Próteses e Materiais Especiais do SUS (SIGTAP) de forma rápida, offline e customizável.

Ao contrário do sistema oficial online, esta ferramenta permite buscas instantâneas, cruzamento de dados complexos via SQL e exportação customizada.

## Funcionalidades Principais

- **Download Automatizado (FTP DataSUS):** Baixa e extrai automaticamente a base de dados mensal (competência) diretamente do servidor oficial do DataSUS.
- **Banco de Dados Local (SQLite):** Converte os arquivos de largura fixa (.txt) do SIGTAP em um banco de dados SQLite otimizado com índices, garantindo buscas em milissegundos.
- **Busca Incremental Inteligente:** Filtros por código, nome, descrição e instrumentos de registro com atualização em tempo real.
- **Visualização de Regras de Faturamento:**
  - **CBOs Habilitados:** Verifica quais ocupações podem realizar determinado procedimento.
  - **Serviços e Classificações:** Consulta exigências de infraestrutura para cada item.
  - **CIDs Globais:** Visualização completa da tabela de CID-10 integrada.
- **Console SQL Avançado:** Editor SQL embutido com _Syntax Highlighting_ (destaque de código) para realizar consultas manuais em todas as tabelas do sistema.
- **Customização de Query Base:** Permite editar a SQL principal do programa. Se você precisar que a tabela principal mostre colunas extras ou cálculos específicos, você pode alterar o motor de busca sem mexer no código-fonte.
- **Exportação:** Gere relatórios em Excel (`.xlsx`) ou CSV com um clique.
- **Portabilidade:** Configurações salvas em arquivo `config.ini` local, facilitando o uso em ambientes sem privilégios de administrador.

## Tecnologias Utilizadas

- **Linguagem:** Python 3.x
- **Interface Gráfica:** PySide6 (Qt for Python)
- **Manipulação de Dados:** Pandas
- **Banco de Dados:** SQLite3
- **Destaque de Sintaxe:** QSyntaxHighlighter personalizado

## Estrutura de Arquivos

- `sigtapviewer.py`: O código-fonte principal da aplicação.
- `sigtap_downloads/`: Pasta gerada automaticamente para armazenar os arquivos brutos do DataSUS.
- `sigtap_local_cache.db`: Gerado dentro da pasta da competência; contém os dados indexados.
- `config.ini`: Armazena suas queries personalizadas e preferências de busca.
- `procedure_cbo_search.log`: Log de erros e operações para diagnóstico. Geralmente fica no `C:\Users\[SeuUsuario]\procedure_cbo_search.log` ou na sua Home no Linux/Mac

## Pré-requisitos

Para rodar o projeto a partir do código-fonte, você precisará das seguintes bibliotecas:

```bash
pip install PySide6 pandas openpyxl chardet
```

## Como Usar

1.  **Primeira Execução:**
    - Selecione a **Competência** (Mês/Ano) desejada.
    - Clique no ícone de **Download (Seta para baixo)**. O programa fará o download, extração e a importação inicial (este processo ocorre apenas uma vez por competência).
    - Alternativamente, se já tiver os arquivos extraídos, clique no ícone da **Pasta** para selecionar o diretório.

2.  **Consultando:**
    - Digite nos campos de busca. Os resultados aparecem automaticamente após 350ms.
    - Clique com o **botão direito** em um procedimento para ver detalhes como CBOs permitidos ou Descrição Completa.

3.  **Customizando a SQL:**
    - Clique no ícone de **Disco Rígido (Config. Busca)**.
    - Edite a query SQL principal. Você pode adicionar JOINs ou filtros permanentes.
    - Clique em "Salvar". O programa passará a usar sua lógica customizada como base para todos os filtros da tela inicial.

4.  **Exportando:**
    - Após filtrar o que deseja, clique no botão de **Salvar (Disquete)** para exportar a grade atual para Excel.

## ⚖️ Licença e Uso de Dados

Este software é uma ferramenta de visualização. Os dados consultados são de domínio público, providos pelo Ministério da Saúde do Brasil através do SIGTAP. O autor não se responsabiliza por decisões financeiras baseadas em dados desatualizados; sempre verifique a competência vigente.

---

**Desenvolvido para facilitar o acesso aos dados do SUS.**
