import sys
import os
import pandas as pd
import unicodedata
import logging
import chardet
import re
import datetime
import ftplib
import fnmatch
import shutil
import zipfile
import sqlite3

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QStatusBar,
    QMenu, QDialog, QTextEdit, QSizePolicy, QDateEdit, QStyle, QListWidget
)
from PySide6.QtCore import Qt, QTimer, QRegularExpression, QSettings 
from PySide6.QtGui import (
    QFont, QKeySequence, QShortcut, QAction,
    QSyntaxHighlighter, QTextCharFormat, QColor 
)

user_home = os.path.expanduser("~")
log_path = os.path.join(user_home, "procedure_cbo_search.log")
logging.basicConfig(filename=log_path, level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_QUERY = """SELECT 
    p.CO_PROCEDIMENTO AS [Código],
    p.NO_PROCEDIMENTO AS [Nome do Procedimento],
    COALESCE(d.DS_PROCEDIMENTO, '') AS [Descrição],
    (SELECT GROUP_CONCAT(r.NO_REGISTRO, ', ') 
     FROM rl_procedimento_registro pr 
     JOIN tb_registro r ON pr.CO_REGISTRO = r.CO_REGISTRO 
     WHERE pr.CO_PROCEDIMENTO = p.CO_PROCEDIMENTO) AS [Instrumentos],
    CASE 
        WHEN CAST(p.VL_SA AS INTEGER) = 0 THEN 'N/A'
        ELSE 'R$ ' || COALESCE(NULLIF(LTRIM(SUBSTR(p.VL_SA, 1, LENGTH(p.VL_SA) - 2), '0'), ''), '0') || ',' || SUBSTR(p.VL_SA, -2)
    END AS [Valor Amb]
FROM tb_procedimento p
LEFT JOIN tb_descricao d ON p.CO_PROCEDIMENTO = d.CO_PROCEDIMENTO
WHERE 1=1"""

class SqlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.mapping = {}
        
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#007AFF"))
        keyword_format.setFontWeight(QFont.Bold)
        keywords =[
            "SELECT", "FROM", "WHERE", "AND", "OR", "JOIN", "LEFT", "INNER", 
            "ON", "GROUP BY", "ORDER BY", "LIMIT", "AS", "IN", "LIKE", "WITH", 
            "COALESCE", "NULL", "IS", "NOT", "MAX", "MIN", "COUNT", "SUM"
        ]
        for word in keywords:
            pattern = QRegularExpression(rf"\b{word}\b")
            pattern.setPatternOptions(QRegularExpression.CaseInsensitiveOption)
            self.mapping[pattern] = keyword_format
            
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#28A745"))
        self.mapping[QRegularExpression(r"'.*?'")] = string_format
        self.mapping[QRegularExpression(r'".*?"')] = string_format
        

    def highlightBlock(self, text):
        for pattern, fmt in self.mapping.items():
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

class SqlConsoleDialog(QDialog):
    def __init__(self, db_conn, parent=None):
        super().__init__(parent)
       
        self.setWindowTitle("Console SQL - SIGTAP")
        self.resize(850, 550)
        self.db_conn = db_conn
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        
        top_area = QHBoxLayout()
        
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("-- Ex: SELECT * FROM tb_procedimento LIMIT 50\n-- Dica: Dê duplo-clique na tabela ao lado para inserir o nome.")
        font_name = "Consolas" if sys.platform == "win32" else "Monospace"
        self.editor.setFont(QFont(font_name, 10))
        top_area.addWidget(self.editor, 4) 
        self.highlighter = SqlHighlighter(self.editor.document())
  
        side_panel = QVBoxLayout()
        side_panel.addWidget(QLabel("Tabelas (2-clique):"))
        self.table_list = QListWidget()
        self.table_list.setFixedWidth(180)
        self.table_list.setToolTip("Duplo-clique para inserir o nome no editor")
        self.table_list.itemDoubleClicked.connect(self.insert_table_name)
        
        self.load_table_names()
        
        side_panel.addWidget(self.table_list)
        top_area.addLayout(side_panel, 1) 
        
        main_layout.addLayout(top_area)
        
        btn_bar = QHBoxLayout()
        run_btn = QPushButton(" Executar (F5)")
        style = QApplication.style()
        run_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        run_btn.clicked.connect(self.run_sql)
        btn_bar.addWidget(run_btn)
        
        exp_btn = QPushButton(" Exportar Resultado")
        exp_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        exp_btn.clicked.connect(lambda: self.parent().export_table_to_excel(self.result_table))
        btn_bar.addWidget(exp_btn)
        
        main_layout.addLayout(btn_bar)

  
        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        main_layout.addWidget(self.result_table)
        

        QShortcut(QKeySequence(Qt.Key_F5), self).activated.connect(self.run_sql)

    def load_table_names(self):
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [row[0] for row in cursor.fetchall()]
            self.table_list.addItems(sorted(tables))
        except Exception as e:
            print(f"Erro ao carregar tabelas: {e}")

    def insert_table_name(self, item):
        self.editor.insertPlainText(item.text())
        self.editor.setFocus()

    def run_sql(self):
        sql = self.editor.toPlainText().strip()
        if not sql: return
        
        if not sql.lower().startswith(("select", "with")):
            if hasattr(self.parent(), 'log_alert'):
                self.parent().log_alert("Apenas consultas (SELECT) são permitidas!", is_error=True)
            return

        try:
            cursor = self.db_conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [d[0] for d in cursor.description]
                data = cursor.fetchall()
                
                self.result_table.setUpdatesEnabled(False)
                self.result_table.setColumnCount(len(cols))
                self.result_table.setRowCount(len(data))
                self.result_table.setHorizontalHeaderLabels(cols)
                
                for r, row_data in enumerate(data):
                    for c, value in enumerate(row_data):
                        val_str = str(value) if value is not None else ""
                        self.result_table.setItem(r, c, QTableWidgetItem(val_str))
                
                self.result_table.setUpdatesEnabled(True)
                self.result_table.resizeColumnsToContents()
                
                if hasattr(self.parent(), 'log_alert'):
                    self.parent().log_alert(f"Sucesso: {len(data)} linhas retornadas.")
            else:
                self.result_table.setRowCount(0)
                
        except Exception as e:
            self.result_table.setUpdatesEnabled(True)
            if hasattr(self.parent(), 'log_alert'):
                self.parent().log_alert(f"Erro SQL: {e}", is_error=True)
class ProcedureCboSearch(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SIGTAP Viewer")
        self.resize(1000, 650)
        
        QApplication.setStyle("Fusion")
    
        self.setStyleSheet("""
            QLineEdit, QPushButton, QDateEdit { 
                padding: 2px 6px; 
                min-height: 22px; 
            }
            QHeaderView::section {
                padding: 2px 4px;
                font-weight: bold;
            }
            QTableWidget {
                gridline-color: palette(midlight);
                margin-top: 0px;
            }
        """)
    
        self.base_path = os.path.dirname(os.path.abspath(__file__ if '__file__' in globals() else sys.executable))
        
       
        self.download_path = os.path.join(self.base_path, "sigtap_downloads")
        os.makedirs(self.download_path, exist_ok=True)
        self.db_conn = None
        config_path = os.path.join(self.base_path, "config.ini")
        self.settings = QSettings(config_path, QSettings.IniFormat)
        self.custom_query = self.settings.value("custom_query", DEFAULT_QUERY)
        self.setup_ui()
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.trigger_search)
        self.dynamic_filters = {} 
        self.last_columns = []  

    def rebuild_filter_ui(self, columns):
        if columns == self.last_columns:
            return
        
        self.last_columns = columns
        
      
        while self.search_layout.count():
            child = self.search_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.dynamic_filters = {}

        for col_name in columns:
            edit = QLineEdit()
            edit.setPlaceholderText(f"Filtrar {col_name}...")
            edit.textChanged.connect(self.on_search_changed)
            
         
            if "Código" in col_name: edit.setFixedWidth(90)
            
            self.search_layout.addWidget(edit)
            self.dynamic_filters[col_name] = edit
            
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

      
        top_layout = QHBoxLayout()
        top_layout.setSpacing(4)
        
      
        self.competencia_input = QDateEdit(datetime.date.today())
        self.competencia_input.setDisplayFormat("MM/yyyy")
        self.competencia_input.setFixedWidth(80)
        self.competencia_input.setToolTip("Competência (Mês/Ano) para baixar do FTP")
        top_layout.addWidget(self.competencia_input)
        
       
        style = QApplication.style()
        icon_download = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        icon_folder = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        icon_list = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        icon_cnfg = style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)
        

        btn_ftp = QPushButton()
        btn_ftp.setIcon(icon_download)
        btn_ftp.setToolTip("Baixar Base SIGTAP via FTP")
        btn_ftp.clicked.connect(self.download_from_ftp)
        top_layout.addWidget(btn_ftp)

        self.folder_input = QLineEdit()
        self.folder_input.setReadOnly(True)
        self.folder_input.setPlaceholderText("Caminho da pasta com TXTs locais...")
        top_layout.addWidget(self.folder_input)
        
        btn_folder = QPushButton()
        btn_folder.setIcon(icon_folder)
        btn_folder.setToolTip("Selecionar Pasta Local")
        btn_folder.clicked.connect(self.select_folder)
        top_layout.addWidget(btn_folder)

        btn_cids = QPushButton()
        btn_cids.setIcon(icon_list)
        btn_cids.setToolTip("Visualizar todos os CIDs Globais")
        btn_cids.clicked.connect(self.show_cids)
        top_layout.addWidget(btn_cids)
        
       
        btn_sql = QPushButton(" SQL")
        btn_sql.setToolTip("Abrir Console SQL Avançado")
        btn_sql.setStyleSheet("font-weight: bold;")
        btn_sql.clicked.connect(self.open_sql_console)
        top_layout.addWidget(btn_sql)
        
        
        btn_config_sql = QPushButton()
        btn_config_sql.setIcon(icon_cnfg)
        btn_sql.setToolTip("Configurar Query Inicial")
        btn_config_sql.clicked.connect(self.open_query_config)
        top_layout.addWidget(btn_config_sql)

        icon_save = style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        btn_export = QPushButton()
        btn_export.setIcon(icon_save)
        btn_export.setToolTip("Exportar tabela atual para Excel/CSV")
        btn_export.clicked.connect(lambda: self.export_table_to_excel(self.table))
        top_layout.addWidget(btn_export)

        main_layout.addLayout(top_layout)

       
        self.search_layout = QHBoxLayout()
        self.search_layout.setSpacing(2) 
        main_layout.addLayout(self.search_layout)

       
        self.table = QTableWidget()
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        main_layout.addWidget(self.table)

       
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

       
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Pronto. Selecione uma pasta para começar.")

       
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_C), self).activated.connect(self.copy_selected)


    def log_alert(self, message, is_error=False):
        logging.info(message) if not is_error else logging.error(message)
        color = "red" if is_error else "#007AFF"
        self.status_bar.setStyleSheet(f"QStatusBar {{ color: {color}; font-weight: bold; }}")
        self.status_bar.showMessage(message, 6000) 
        QTimer.singleShot(6000, lambda: self.status_bar.setStyleSheet("QStatusBar { color: #333; }"))

    def detect_encoding(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                result = chardet.detect(f.read(10000))
                return result['encoding'] or 'latin1'
        except Exception:
            return 'latin1'

    def open_query_config(self):
        if not self.db_conn:
            self.log_alert("Carregue os dados primeiro!", is_error=True)
            return
            
        dlg = QDialog(self)
        dlg.setWindowTitle("Customizar SQL de Busca Inicial")
        dlg.resize(750, 450)
        lay = QVBoxLayout(dlg)
        
        editor = QTextEdit()
        self.highlighter = SqlHighlighter(editor.document())
        editor.setPlainText(self.custom_query)
        
        lay.addWidget(QLabel("Edite a query base (mantenha os nomes das colunas entre [ ] para os filtros funcionarem):"))
        lay.addWidget(editor)
        
        btn_bar = QHBoxLayout()
        
        btn_reset = QPushButton("Resetar para Padrão")
        btn_reset.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        btn_reset.clicked.connect(lambda: editor.setPlainText(DEFAULT_QUERY)) 
        
        btn_save = QPushButton("Salvar e Aplicar")
        btn_save.setStyleSheet("font-weight: bold;")
        btn_save.clicked.connect(dlg.accept)
        
        btn_bar.addWidget(btn_reset)
        btn_bar.addStretch() 
        btn_bar.addWidget(btn_save)
        
        lay.addLayout(btn_bar)
        
        if dlg.exec() == QDialog.Accepted:
            nova_query = editor.toPlainText()
            if not nova_query.strip().lower().startswith("select"):
                self.log_alert("A query base deve ser um SELECT!", is_error=True)
                return
        
            self.custom_query = nova_query
            self.settings.setValue("custom_query", self.custom_query) 
            self.dynamic_filters = {}
            self.last_columns = []
            self.trigger_search()
            self.log_alert("Nova query base aplicada e salva!")



    def copy_selected(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            return

     
        selection_map = {}
        for item in selected_items:
            r, c = item.row(), item.column()
            
          
            val = item.data(Qt.UserRole)
            if val is None:
                val = item.text()
                
            if r not in selection_map:
                selection_map[r] = {}
            selection_map[r][c] = val

      
        lines = []
        for r in sorted(selection_map.keys()):
            row_data = selection_map[r]
         
            row_text = [row_data[c] for c in sorted(row_data.keys())]
            lines.append("\t".join(row_text))

        full_text = "\n".join(lines)
        QApplication.clipboard().setText(full_text)
        
     
        count = len(selected_items)
        self.log_alert(f"{count} célula(s) copiada(s) para o clipboard.")



    def on_search_changed(self):
        self.search_timer.start(350) 

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta com arquivos TXT do SIGTAP")
        if folder:
            self.folder_input.setText(folder)
            self.ensure_database_loaded(folder)


    def ensure_database_loaded(self, folder_path):
        db_path = os.path.join(folder_path, "sigtap_local_cache.db")
        self.db_conn = sqlite3.connect(db_path, check_same_thread=False)

       
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tb_procedimento'")
        if cursor.fetchone():
            self.log_alert("Banco de dados em cache encontrado. Carregamento instantâneo!")
            self.trigger_search()
            return

      
        layout_map = {
            'tb_procedimento': ('tb_procedimento_layout.txt', 'tb_procedimento.txt'),
            'tb_descricao': ('tb_descricao_layout.txt', 'tb_descricao.txt'),
            'rl_procedimento_ocupacao': ('rl_procedimento_ocupacao_layout.txt', 'rl_procedimento_ocupacao.txt'),
            'tb_ocupacao': ('tb_ocupacao_layout.txt', 'tb_ocupacao.txt'),
            'tb_registro': ('tb_registro_layout.txt', 'tb_registro.txt'),
            'rl_procedimento_registro': ('rl_procedimento_registro_layout.txt', 'rl_procedimento_registro.txt'),
            'tb_cid': ('tb_cid_layout.txt', 'tb_cid.txt'),
            'tb_servico': ('tb_servico_layout.txt', 'tb_servico.txt'),
            'tb_servico_classificacao': ('tb_servico_classificacao_layout.txt', 'tb_servico_classificacao.txt'),
            'rl_procedimento_servico': ('rl_procedimento_servico_layout.txt', 'rl_procedimento_servico.txt')
        }

        self.progress_bar.show()
        self.progress_bar.setValue(0)
        total_files = len(layout_map)
        
        self.log_alert("Construindo banco de dados local a partir dos TXTs (Isso é feito apenas uma vez)...")

        for idx, (table_name, (layout_file, data_file)) in enumerate(layout_map.items()):
            l_path = os.path.join(folder_path, layout_file)
            d_path = os.path.join(folder_path, data_file)
            
            if not os.path.exists(l_path) or not os.path.exists(d_path):
                logging.warning(f"Arquivos ausentes para {table_name}")
                continue

            try:
                with open(l_path, 'r', encoding='latin1') as f:
                    lines =[line.strip().split(',') for line in f.readlines() if line.strip()]
                columns, sizes = [],[]
                for parts in lines[1:]: 
                    if len(parts) >= 2:
                        columns.append(parts[0].strip())
                        sizes.append(int(parts[1].strip()))


                encoding = self.detect_encoding(d_path)
                df = pd.read_fwf(d_path, widths=sizes, names=columns, encoding=encoding, dtype=str)
                df = df.apply(lambda x: x.str.strip() if x.dtype == 'object' else x)
                df.to_sql(table_name, self.db_conn, if_exists='replace', index=False)

                self.progress_bar.setValue(int(((idx + 1) / total_files) * 100))
                QApplication.processEvents()
            except Exception as e:
                self.log_alert(f"Erro ao processar {table_name}: {e}", is_error=True)

        try:
            self.db_conn.execute("CREATE INDEX idx_proc ON tb_procedimento(CO_PROCEDIMENTO)")
            self.db_conn.execute("CREATE INDEX idx_desc ON tb_descricao(CO_PROCEDIMENTO)")
            self.db_conn.execute("CREATE INDEX idx_rel_reg ON rl_procedimento_registro(CO_PROCEDIMENTO)")
        except Exception as e:
            pass 

        self.progress_bar.hide()
        self.log_alert("Importação finalizada com sucesso! Banco de dados local criado.")
        self.trigger_search()

    def normalize_str(self, val):
        if not val: return ""
        val = unicodedata.normalize('NFKD', val).encode('ASCII', 'ignore').decode('ASCII').lower()
        return f"%{val}%"

    def trigger_search(self):
        if not self.db_conn: return
        self.table.setRowCount(0)
        self.perform_search()

    def perform_search(self):
        if not self.db_conn: return
        

        if not self.dynamic_filters:
            cursor = self.db_conn.cursor()
            cursor.execute(f"SELECT * FROM ({self.custom_query}) AS base LIMIT 0")
            cols = [desc[0] for desc in cursor.description]
            self.rebuild_filter_ui(cols)


        base_query = f"SELECT * FROM ({self.custom_query}) AS base WHERE 1=1"
        params = []
        for col_name, edit in self.dynamic_filters.items():
            text = edit.text().strip()
            if text:
                base_query += f" AND [{col_name}] LIKE ?"
                params.append(f"%{text}%")
                
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(base_query, params)
            data = cursor.fetchall()
            current_cols = [desc[0] for desc in cursor.description]

            if current_cols != self.last_columns:
                self.rebuild_filter_ui(current_cols)
               
            self.table.setUpdatesEnabled(False)
            self.table.setColumnCount(len(current_cols))
            self.table.setHorizontalHeaderLabels(current_cols)
            self.table.setRowCount(len(data))

            for r_idx, row_values in enumerate(data):
                for c_idx, col_name in enumerate(current_cols):
                    val = row_values[c_idx]
                    val_str = str(val) if val is not None else ""
                    item = QTableWidgetItem()
                    
                    if "Descrição" in col_name:
                        short_text = val_str[:120] + ("..." if len(val_str) > 120 else "")
                        item.setText(short_text)
                        item.setData(Qt.UserRole, val_str) 
                    else:
                        item.setText(val_str)
                    self.table.setItem(r_idx, c_idx, item)

            
            num_cols = self.table.columnCount()
            
            if num_cols > 0:
                header = self.table.horizontalHeader()
                total_width = (self.table.viewport().width()) - 100
                width_per_col = total_width // num_cols 
                
                for i in range(num_cols):
                    self.table.setColumnWidth(i, width_per_col)
                    header.setSectionResizeMode(i, QHeaderView.Interactive)
                    
                header.setStretchLastSection(True)
                self.table.setUpdatesEnabled(True)
                self.log_alert(f"{len(data)} resultados encontrados.")
            
        except Exception as e:
            self.table.setUpdatesEnabled(True)
            self.log_alert(f"Erro: {e}", is_error=True)          
    def on_scroll(self, value):
        bar = self.table.verticalScrollBar()
        if value >= bar.maximum() - 15:
            self.load_more_data()


    def show_context_menu(self, position):
        item = self.table.itemAt(position)
        if not item: return
        
        row = item.row()
        col_idx_code = -1
        col_idx_desc = -1
        for c in range(self.table.columnCount()):
            header_text = self.table.horizontalHeaderItem(c).text()
            if "Código" in header_text: col_idx_code = c
            if "Descrição" in header_text: col_idx_desc = c

        co_proc = self.table.item(row, col_idx_code).text() if col_idx_code != -1 else ""
       
        full_desc = self.table.item(row, col_idx_desc).data(Qt.UserRole) if col_idx_desc != -1 else ""
        
        menu = QMenu(self)

        act_desc = QAction("Ler Descrição Completa", self)
        act_cbo = QAction("Ver CBOs Habilitados", self)
        act_serv = QAction("Ver Serviços/Classificações Exigidas", self)

        menu.addAction(act_desc)
        menu.addAction(act_cbo)
        menu.addAction(act_serv)

        action = menu.exec(self.table.viewport().mapToGlobal(position))
        
        if action == act_desc:
            self.show_dialog_text("Descrição Completa", full_desc)
        elif action == act_cbo:
            self.show_cbos(co_proc)
        elif action == act_serv:
            self.show_servicos(co_proc)

    def show_dialog_text(self, title, text):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(500, 300)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit(text)
        txt.setReadOnly(True)
        lay.addWidget(txt)
        btn = QPushButton("Fechar")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

    def show_cbos(self, co_proc):
        query = """
            SELECT o.CO_OCUPACAO, o.NO_OCUPACAO 
            FROM rl_procedimento_ocupacao po 
            JOIN tb_ocupacao o ON po.CO_OCUPACAO = o.CO_OCUPACAO 
            WHERE po.CO_PROCEDIMENTO = ?
        """
        cursor = self.db_conn.cursor()
        cursor.execute(query, (co_proc,))
        results = cursor.fetchall()

        if not results:
            self.log_alert(f"O procedimento {co_proc} é liberado para qualquer CBO (Sem exigência).")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"CBOs Habilitados - {co_proc}")
        dlg.resize(600, 400)
        lay = QVBoxLayout(dlg)
        
        t = QTableWidget(len(results), 2)
        t.setHorizontalHeaderLabels(["Código", "Ocupação"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for i, row in enumerate(results):
            t.setItem(i, 0, QTableWidgetItem(str(row[0])))
            t.setItem(i, 1, QTableWidgetItem(str(row[1])))
        
        lay.addWidget(t)
        dlg.exec()

    def show_servicos(self, co_proc):
        query = """
            SELECT s.CO_SERVICO, s.NO_SERVICO, c.CO_CLASSIFICACAO, c.NO_CLASSIFICACAO 
            FROM rl_procedimento_servico ps
            LEFT JOIN tb_servico s ON ps.CO_SERVICO = s.CO_SERVICO
            LEFT JOIN tb_servico_classificacao c ON ps.CO_SERVICO = c.CO_SERVICO AND ps.CO_CLASSIFICACAO = c.CO_CLASSIFICACAO
            WHERE ps.CO_PROCEDIMENTO = ?
        """
        cursor = self.db_conn.cursor()
        cursor.execute(query, (co_proc,))
        results = cursor.fetchall()

        if not results:
            self.log_alert(f"O procedimento {co_proc} não exige serviço ou classificação específica.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Serviços e Classificações - {co_proc}")
        dlg.resize(800, 400)
        lay = QVBoxLayout(dlg)
        
        t = QTableWidget(len(results), 4)
        t.setHorizontalHeaderLabels(["Cód Serv.", "Serviço", "Cód Classif.", "Classificação"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for i, row in enumerate(results):
            t.setItem(i, 0, QTableWidgetItem(str(row[0] or "")))
            t.setItem(i, 1, QTableWidgetItem(str(row[1] or "Sem nome")))
            t.setItem(i, 2, QTableWidgetItem(str(row[2] or "")))
            t.setItem(i, 3, QTableWidgetItem(str(row[3] or "Sem classificação")))
        
        lay.addWidget(t)
        dlg.exec()

    def show_cids(self):
        if not self.db_conn:
            self.log_alert("Carregue uma pasta primeiro para ver os CIDs", is_error=True)
            return
            
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT CO_CID, NO_CID, TP_AGRAVO, TP_SEXO FROM tb_cid LIMIT 5000")
        results = cursor.fetchall()
        
        dlg = QDialog(self)
        dlg.setWindowTitle("Lista Global de CIDs")
        dlg.resize(800, 500)
        lay = QVBoxLayout(dlg)
        
        t = QTableWidget(len(results), 4)
        t.setHorizontalHeaderLabels(["CID", "Descrição", "Agravo", "Sexo Permitido"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for i, row in enumerate(results):
            t.setItem(i, 0, QTableWidgetItem(str(row[0])))
            t.setItem(i, 1, QTableWidgetItem(str(row[1])))
            t.setItem(i, 2, QTableWidgetItem(str(row[2])))
            t.setItem(i, 3, QTableWidgetItem(str(row[3])))
            
        lay.addWidget(t)
        dlg.exec()
        
    def open_sql_console(self):
        if not self.db_conn:
            self.log_alert("Selecione uma pasta com dados primeiro!", is_error=True)
            return
        self.sql_win = SqlConsoleDialog(self.db_conn, self)
        self.sql_win.show()

    def export_table_to_excel(self, table_widget):
        if table_widget.rowCount() == 0:
            self.log_alert("Tabela vazia!", is_error=True)
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar Arquivo", "", "Excel (*.xlsx);;CSV (*.csv)"
        )
        if not path: return

        try:
            self.log_alert("Exportando...")
            cols = table_widget.columnCount()
            rows = table_widget.rowCount()
            headers = [table_widget.horizontalHeaderItem(i).text() for i in range(cols)]
            
            data = []
            for r in range(rows):
                row_data = []
                for c in range(cols):
                    it = table_widget.item(r, c)
                    row_data.append(it.text() if it else "")
                data.append(row_data)

            df = pd.DataFrame(data, columns=headers)
            
            if path.endswith('.xlsx'):
                df.to_excel(path, index=False)
            else:
                df.to_csv(path, index=False, sep=';', encoding='latin1')
                
            self.log_alert(f"Salvo em: {os.path.basename(path)}")
        except Exception as e:
            self.log_alert(f"Erro ao salvar: {e}", is_error=True)


    def download_from_ftp(self):
        competencia = self.competencia_input.date().toString("yyyyMM")
        if not re.match(r"^\d{6}$", competencia):
            self.log_alert("A competência deve ser no formato AAAAMM (ex: 202402)", is_error=True)
            return
            
        ftp_host = "ftp2.datasus.gov.br"
        ftp_path = "/pub/sistemas/tup/downloads/"
        zip_pattern = f"TabelaUnificada_{competencia}*.zip"
        download_subpath = os.path.join(self.download_path, competencia)
        
        try:
            self.progress_bar.show()
            self.log_alert("Conectando ao DataSUS FTP...")
            QApplication.processEvents()
            
            ftp = ftplib.FTP(ftp_host)
            ftp.login()
            ftp.cwd(ftp_path)
            
            files = ftp.nlst()
            zip_file = next((f for f in files if fnmatch.fnmatch(f, zip_pattern)), None)
            
            if not zip_file:
                self.log_alert(f"Nenhum arquivo encontrado para a competência {competencia}.", is_error=True)
                ftp.quit()
                self.progress_bar.hide()
                return

            os.makedirs(download_subpath, exist_ok=True)
            zip_path = os.path.join(download_subpath, zip_file)
            
            self.log_alert(f"Baixando {zip_file}... (Pode demorar alguns minutos)")
            with open(zip_path, 'wb') as f:
                ftp.retrbinary(f"RETR {zip_file}", f.write)
            ftp.quit()
            
            self.log_alert("Extraindo arquivos ZIP...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(download_subpath)
            os.remove(zip_path) 
            
            self.progress_bar.hide()
            self.log_alert("Download e extração concluídos!")
            
           
            self.folder_input.setText(download_subpath)
            self.ensure_database_loaded(download_subpath)
            
        except Exception as e:
            self.progress_bar.hide()
            self.log_alert(f"Falha na rotina FTP: {e}", is_error=True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ProcedureCboSearch()
    window.show()
    sys.exit(app.exec())