# ⚡ Otimizador do Windows & PC v5.0

Aplicativo nativo para Windows em Python, desenvolvido para limpeza profunda, liberação de espaço em disco e otimização de desempenho do sistema, **sem dependências externas** (utiliza apenas bibliotecas padrão do Python e APIs nativas do Windows).

---

## 🚀 Recursos Principais

### 🖥️ Limpeza do Sistema Windows
- **Arquivos temporários do usuário:** Limpeza completa da pasta `%TEMP%`.
- **Arquivos temporários do sistema:** Limpeza da pasta `C:\Windows\Temp`.
- **Lixeira do Windows:** Esvaziamento seguro através da API Shell32 nativa (`SHEmptyRecycleBinW`).
- **Cache de miniaturas:** Remoção de `thumbcache_*.db` e `iconcache_*.db` do Windows Explorer.
- **Relatórios de falhas e erros:** Limpeza de `CrashDumps` e relatórios WER (`ReportArchive` e `ReportQueue`).
- **Cálculo de espaço liberado:** Contabilização precisa do total de bytes (B, KB, MB, GB) e número de arquivos removidos.

### 🌐 Limpeza e Compactação de Navegadores
- **Navegadores suportados:** Google Chrome, Microsoft Edge, Brave Browser, Opera, Opera GX, Vivaldi e Mozilla Firefox.
- **Limpeza completa do histórico:** Remoção de URLs, visitas, buscas e histórico de downloads com execução de comando `VACUUM` no SQLite para compactar e desfragmentar a base.
- **Limpeza de cache web:** Remoção de pastas de cache (`Cache`, `Code Cache`, `GPUCache`, `DawnCache`, `cache2`, `startupCache`) que liberam gigabytes de espaço.
- **Segurança e privacidade:** Favoritos, senhas salvas, cookies e dados de sessão são preservados.
- **Detecção de processos:** Identifica se os navegadores estão em execução e oferece fechamento automático para evitar erros de banco de dados bloqueado.

### ⚡ Otimização do PC ("Rodando Lisinho")
- **Limpeza de cache DNS:** Execução silenciosa de `ipconfig /flushdns` para resolver problemas de conexão e lentidão de rede.
- **Otimização de memória RAM:** Redução do consumo de memória RAM do sistema através de trim de working sets (`SetProcessWorkingSetSize`).

### 🎨 Interface Gráfica Moderna e Responsiva
- **Dark Mode moderno:** Interface elegante construída com Tkinter e TTK customizado.
- **Execução multithread:** A interface gráfica nunca congela ou apresenta "Não Respondendo" durante a limpeza.
- **Console em tempo real:** Terminal integrado exibindo detalhes e progresso passo a passo das tarefas.
- **Modo Análise Prévia:** Botão para escanear e estimar o espaço a ser liberado antes de iniciar a limpeza.
- **Predefinições rápidas:** Botões "Marcar Tudo", "Recomendado" e "Desmarcar Tudo".

---

## 💻 Como Executar

Abra o PowerShell nesta pasta e execute:

```powershell
python app.py
```

*Não é necessário instalar nenhum pacote via `pip`.*

---

## 🧪 Executar Testes Unitários

Para rodar a suíte completa de testes automatizados:

```powershell
python -m unittest -v
```
