"""
Ventana principal para visualización de análisis fundamental
"""
import sys
import json
from pathlib import Path
from typing import List, Dict, Optional

from PyQt5 import QtCore, QtWidgets, QtGui

from ..core import FundamentalAnalysisEngine, load_config, connect_nats
from ..utils import setup_logging, get_logger
from .widgets import ValuationTree, DetailDialog


class AnalysisWorker(QtCore.QThread):
    """Worker thread para ejecutar análisis en segundo plano"""
    result_ready = QtCore.pyqtSignal(dict)  # Emite cada resultado cuando está listo
    progress_update = QtCore.pyqtSignal(str)  # Emite actualizaciones de progreso
    finished = QtCore.pyqtSignal(list)  # Emite cuando termina todo
    
    def __init__(self, engine: FundamentalAnalysisEngine, symbols: List[str]):
        super().__init__()
        self.engine = engine
        self.symbols = symbols
    
    def run(self):
        """Ejecuta el análisis y emite resultados uno por uno"""
        results = []
        
        try:
            # Primero filtrar por surprise EPS positivo
            filtered_companies = self.engine.filter_companies_with_positive_surprise(self.symbols)
            total = len(filtered_companies)
            
            if total == 0:
                self.progress_update.emit("No se encontraron empresas con surprise EPS positivo")
                self.finished.emit([])
                return
            
            self.progress_update.emit(f"Encontradas {total} empresas con surprise EPS positivo")
            
            for idx, company in enumerate(filtered_companies):
                symbol = company["symbol"]
                surprise = company.get("surprise_eps")
                
                self.progress_update.emit(f"Analizando {symbol} ({idx+1}/{total})...")
                
                # Calcular valoración para este símbolo
                valuation = self.engine.calculate_valuation_for_symbol(symbol, surprise)
                
                if valuation:
                    # Determinar decisión de compra
                    buy_decision = self.engine.buy_decision.should_buy(surprise, valuation)
                    
                    # Convertir a dict y agregar decisión de compra
                    if hasattr(valuation, 'to_dict'):
                        result_dict = valuation.to_dict()
                    elif isinstance(valuation, dict):
                        result_dict = valuation
                    else:
                        continue
                    
                    # Mapear campos para compatibilidad con UI
                    # La UI espera 'intrinsic_value' pero ValuationResult tiene 'blended_fair_value'
                    if 'blended_fair_value' in result_dict and 'intrinsic_value' not in result_dict:
                        result_dict['intrinsic_value'] = result_dict['blended_fair_value']
                    if 'undervaluation_percentage' in result_dict and 'valuation_percentage' not in result_dict:
                        result_dict['valuation_percentage'] = result_dict['undervaluation_percentage']
                    
                    # Agregar decisión de compra
                    result_dict["buy"] = buy_decision
                    
                    # Emitir resultado inmediatamente
                    self.result_ready.emit(result_dict)
                    results.append(result_dict)
                
                # Procesar eventos para mantener UI responsive
                QtCore.QThread.msleep(100)
            
            self.progress_update.emit("Análisis completado")
            self.finished.emit(results)
            
        except Exception as e:
            self.progress_update.emit(f"Error: {str(e)}")
            self.finished.emit(results)


class MainWindow(QtWidgets.QMainWindow):
    """Ventana principal de análisis fundamental"""
    
    REFRESH_INTERVAL_MS = 30000  # 30 segundos
    
    def __init__(self, config_path: str = "settings.ini"):
        super().__init__()
        self.config_path = config_path
        self.logger = setup_logging()
        
        self.setWindowTitle("Fundamental Analysis - Alpha Spread Style")
        self.resize(1200, 700)
        
        # Asegurar que la ventana se muestre correctamente
        self.setWindowFlags(QtCore.Qt.Window)
        
        # Resultados actuales
        self._current_results: List[Dict] = []
        
        # Crear árbol de resultados
        self._tree = ValuationTree(self)
        self._tree.itemDoubleClicked.connect(self._show_detail)
        
        # Controles superiores
        controls_widget = QtWidgets.QWidget(self)
        controls_layout = QtWidgets.QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)
        
        # Botón de análisis
        self._analyze_btn = QtWidgets.QPushButton("🔍 Analizar Empresas", controls_widget)
        self._analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self._analyze_btn.clicked.connect(self._run_analysis)
        
        # Botón de carga desde archivo
        self._load_btn = QtWidgets.QPushButton("📂 Cargar desde Archivo", controls_widget)
        self._load_btn.clicked.connect(self._load_from_file)
        
        # Filtros
        self._buy_filter = QtWidgets.QComboBox(controls_widget)
        self._buy_filter.addItem("Todas", None)
        self._buy_filter.addItem("✅ Comprar", True)
        self._buy_filter.addItem("❌ No Comprar", False)
        
        self._symbol_filter = QtWidgets.QLineEdit(controls_widget)
        self._symbol_filter.setPlaceholderText("Filtrar símbolo...")
        
        controls_layout.addWidget(self._analyze_btn)
        controls_layout.addWidget(self._load_btn)
        controls_layout.addWidget(QtWidgets.QLabel("Filtro:", controls_widget))
        controls_layout.addWidget(self._buy_filter)
        controls_layout.addWidget(QtWidgets.QLabel("Símbolo:", controls_widget))
        controls_layout.addWidget(self._symbol_filter)
        controls_layout.addStretch()
        
        # Conectar filtros
        self._buy_filter.currentIndexChanged.connect(self._update_filtered_results)
        self._symbol_filter.textChanged.connect(self._update_filtered_results)
        
        # Layout principal
        container = QtWidgets.QWidget(self)
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(8)
        container_layout.addWidget(controls_widget)
        container_layout.addWidget(self._tree)
        
        self.setCentralWidget(container)
        
        # Status bar
        self._status_label = QtWidgets.QLabel("Listo para analizar")
        self.statusBar().addPermanentWidget(self._status_label)
        
        # Timer para auto-refresh (opcional)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._auto_refresh)
        
        # Cargar configuración
        self._config = load_config(config_path)
        
        # Crear engine (sin NATS para UI standalone)
        api_key = self._config.get("finnhub_api_key", "")
        if api_key and api_key != "YOUR_API_KEY_HERE":
            self._engine = FundamentalAnalysisEngine(api_key, logger=self.logger)
        else:
            self._engine = None
            self.statusBar().showMessage("⚠️ Configura tu API key de Finnhub en settings.ini", 10000)
        
        # Worker thread para análisis en segundo plano
        self._analysis_worker = None
    
    def _run_analysis(self):
        """Ejecuta análisis de empresas en segundo plano"""
        if not self._engine:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                "No se puede ejecutar análisis.\n"
                "Configura tu API key de Finnhub en settings.ini"
            )
            return
        
        symbols = self._config.get("symbols", [])
        if not symbols:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                "No hay símbolos configurados.\n"
                "Agrega símbolos en la sección [SYMBOLS] de settings.ini"
            )
            return
        
        # Si ya hay un análisis corriendo, no hacer nada
        if self._analysis_worker and self._analysis_worker.isRunning():
            return
        
        # Limpiar resultados anteriores
        self._current_results = []
        self._tree.clear()
        
        # Deshabilitar botón
        self._analyze_btn.setEnabled(False)
        self.statusBar().showMessage("Iniciando análisis...")
        
        # Crear y configurar worker thread
        self._analysis_worker = AnalysisWorker(self._engine, symbols)
        self._analysis_worker.result_ready.connect(self._on_result_ready)
        self._analysis_worker.progress_update.connect(self._on_progress_update)
        self._analysis_worker.finished.connect(self._on_analysis_finished)
        
        # Iniciar análisis en segundo plano
        self._analysis_worker.start()
    
    def _on_result_ready(self, result: Dict):
        """Se llama cuando un resultado está listo - actualiza UI inmediatamente"""
        # Agregar resultado a la lista
        self._current_results.append(result)
        
        # Actualizar árbol inmediatamente
        self._update_filtered_results()
        
        # Actualizar status bar
        symbol = result.get("symbol", "Unknown")
        buy = result.get("buy", False)
        buy_text = "✅ COMPRAR" if buy else "❌ NO COMPRAR"
        self.statusBar().showMessage(f"📊 {symbol}: {buy_text} | Valor: ${result.get('blended_fair_value', 0):.2f}")
    
    def _on_progress_update(self, message: str):
        """Se llama cuando hay una actualización de progreso"""
        self.statusBar().showMessage(message)
        QtWidgets.QApplication.processEvents()  # Mantener UI responsive
    
    def _on_analysis_finished(self, results: List[Dict]):
        """Se llama cuando el análisis termina"""
        self._current_results = results
        self._update_filtered_results()
        
        buy_count = sum(1 for r in results if r.get("buy", False))
        self.statusBar().showMessage(
            f"✅ Análisis completado: {len(results)} empresas | "
            f"{buy_count} recomendaciones de compra"
        )
        
        # Rehabilitar botón
        self._analyze_btn.setEnabled(True)
        self._analysis_worker = None
    
    def _load_from_file(self):
        """Carga resultados desde archivo JSON"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Cargar resultados",
            "",
            "JSON Files (*.json)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if "results" in data:
                self._current_results = data["results"]
            else:
                self._current_results = data if isinstance(data, list) else []
            
            self._update_filtered_results()
            
            self.statusBar().showMessage(
                f"✅ Cargados {len(self._current_results)} resultados desde {Path(file_path).name}"
            )
            
        except Exception as e:
            self.logger.error(f"Error cargando archivo: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Error al cargar archivo:\n{str(e)}"
            )
    
    def _update_filtered_results(self):
        """Actualiza resultados filtrados"""
        filtered = list(self._current_results)
        
        # Filtro por decisión de compra
        buy_filter_value = self._buy_filter.currentData()
        if buy_filter_value is not None:
            filtered = [r for r in filtered if r.get("buy") == buy_filter_value]
        
        # Filtro por símbolo
        symbol_text = self._symbol_filter.text().strip().lower()
        if symbol_text:
            filtered = [r for r in filtered if symbol_text in r.get("symbol", "").lower()]
        
        # Actualizar árbol
        self._tree.update_results(filtered)
        
        # Actualizar status
        total = len(self._current_results)
        showing = len(filtered)
        buy_count = sum(1 for r in filtered if r.get("buy", False))
        
        self._status_label.setText(
            f"Total: {total} | Mostrando: {showing} | Comprar: {buy_count}"
        )
    
    def _show_detail(self, item: QtWidgets.QTreeWidgetItem, column: int):
        """Muestra diálogo con detalles completos"""
        result = self._tree.result_from_item(item)
        if not result:
            return
        
        dialog = DetailDialog(result, self)
        dialog.exec_()
    
    def _auto_refresh(self):
        """Auto-refresh opcional (deshabilitado por defecto)"""
        # Puede habilitarse si se quiere auto-refresh periódico
        pass
    
    def closeEvent(self, event):
        """Cierra la ventana"""
        self._timer.stop()
        
        # Esperar a que termine el análisis si está corriendo
        if self._analysis_worker and self._analysis_worker.isRunning():
            self._analysis_worker.terminate()
            self._analysis_worker.wait()
        
        super().closeEvent(event)


def main():
    """Función principal para ejecutar la UI"""
    print("=" * 60)
    print("Iniciando Fundamental Analysis UI...")
    print("=" * 60)
    
    # Verificar que no haya otra instancia corriendo
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        print("✓ QApplication creado")
    else:
        print("✓ QApplication ya existe")
    
    # Estilo moderno
    app.setStyle("Fusion")
    
    # Configurar paleta de colores
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtCore.Qt.white)
    app.setPalette(palette)
    
    print("✓ Estilo y paleta configurados")
    
    window = MainWindow()
    print("✓ MainWindow creada")
    
    window.show()
    window.raise_()  # Traer al frente
    window.activateWindow()  # Activar ventana
    print("✓ Ventana mostrada y activada")
    print("=" * 60)
    print("Si no ves la ventana:")
    print("1. Presiona Alt+Tab para buscarla")
    print("2. Verifica que no esté minimizada")
    print("3. Busca 'Fundamental Analysis' en la barra de tareas")
    print("=" * 60)
    
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())

