"""
Widgets para visualización de análisis fundamental
"""
from typing import Dict, List, Optional
from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets


class ValuationTree(QtWidgets.QTreeWidget):
    """Árbol para mostrar resultados de valoración"""
    
    ENTRY_ROLE = QtCore.Qt.UserRole + 1
    HEADERS = ["Símbolo", "Decisión", "Precio", "Valor Intrínseco", "Valoración %", "Status"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHeaderLabels(self.HEADERS)
        self.setRootIsDecorated(True)
        self.setIndentation(18)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setUniformRowHeights(False)
        self.setAnimated(True)
        
        # Configurar header
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)  # Símbolo
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)  # Decisión
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)  # Precio
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)  # Valor Intrínseco
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)  # Valoración %
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)  # Status
        
        self._items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._placeholder_item: Optional[QtWidgets.QTreeWidgetItem] = None
        self._ensure_placeholder()
    
    def update_results(self, results: List[Dict]):
        """Actualiza el árbol con nuevos resultados"""
        if results:
            self._remove_placeholder()
        else:
            self._ensure_placeholder()
            return
        
        seen_symbols = set()
        
        for result in results:
            symbol = result.get("symbol", "")
            seen_symbols.add(symbol)
            
            item = self._items.get(symbol)
            if item is None:
                item = QtWidgets.QTreeWidgetItem(self)
                self._items[symbol] = item
            
            self._apply_result_to_item(item, result)
        
        # Remover items que ya no están
        for symbol in list(self._items.keys()):
            if symbol not in seen_symbols:
                item = self._items.pop(symbol)
                index = self.indexOfTopLevelItem(item)
                if index != -1:
                    self.takeTopLevelItem(index)
        
        if not self._items:
            self._ensure_placeholder()
        
        self.sortItems(4, QtCore.Qt.DescendingOrder)  # Ordenar por valoración %
        self.expandAll()
    
    def _apply_result_to_item(self, item: QtWidgets.QTreeWidgetItem, result: Dict):
        """Aplica un resultado a un item del árbol"""
        symbol = result.get("symbol", "")
        buy = result.get("buy", False)
        current_price = result.get("current_price", 0)
        intrinsic_value = result.get("intrinsic_value", 0)
        valuation_pct = result.get("valuation_percentage", 0)
        status = result.get("status", "")
        surprise_eps = result.get("surprise_eps", 0)
        
        # Símbolo
        item.setText(0, symbol)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        
        # Decisión (COMPRAR / NO COMPRAR)
        decision_text = "✅ COMPRAR" if buy else "❌ NO COMPRAR"
        item.setText(1, decision_text)
        
        # Colores según decisión
        if buy:
            item.setForeground(1, QtGui.QBrush(QtGui.QColor(0, 150, 0)))  # Verde
            item.setBackground(1, QtGui.QBrush(QtGui.QColor(230, 255, 230)))  # Fondo verde claro
        else:
            item.setForeground(1, QtGui.QBrush(QtGui.QColor(200, 0, 0)))  # Rojo
            item.setBackground(1, QtGui.QBrush(QtGui.QColor(255, 230, 230)))  # Fondo rojo claro
        
        # Precio actual
        item.setText(2, f"${current_price:.2f}")
        
        # Valor intrínseco
        item.setText(3, f"${intrinsic_value:.2f}")
        
        # Valoración %
        valuation_text = f"{valuation_pct:+.1f}%"
        item.setText(4, valuation_text)
        
        # Color según valoración
        if valuation_pct > 25:
            item.setForeground(4, QtGui.QBrush(QtGui.QColor(0, 150, 0)))  # Verde oscuro
        elif valuation_pct > 0:
            item.setForeground(4, QtGui.QBrush(QtGui.QColor(0, 100, 200)))  # Azul
        elif valuation_pct > -5:
            item.setForeground(4, QtGui.QBrush(QtGui.QColor(100, 100, 100)))  # Gris
        else:
            item.setForeground(4, QtGui.QBrush(QtGui.QColor(200, 0, 0)))  # Rojo
        
        # Status
        status_map = {
            "undervalued": "🔵 Infravalorada",
            "slightly_undervalued": "🟢 Ligeramente Infravalorada",
            "fair": "⚖️ Valor Justo",
            "slightly_overvalued": "🟡 Ligeramente Sobrevalorada",
            "overvalued": "🔴 Sobrevalorada"
        }
        status_text = status_map.get(status, status)
        item.setText(5, status_text)
        
        # Tooltip con información detallada
        tooltip = (
            f"Símbolo: {symbol}\n"
            f"Decisión: {'COMPRAR' if buy else 'NO COMPRAR'}\n"
            f"Precio Actual: ${current_price:.2f}\n"
            f"Valor Intrínseco: ${intrinsic_value:.2f}\n"
            f"Valoración: {valuation_pct:+.2f}%\n"
            f"Status: {status}\n"
            f"Surprise EPS: {surprise_eps:+.2f}\n"
            f"DCF Base: ${result.get('dcf_base', 0):.2f}\n"
            f"DCF Pesimista: ${result.get('dcf_pessimistic', 0):.2f}\n"
            f"DCF Optimista: ${result.get('dcf_optimistic', 0):.2f}\n"
            f"Comparables: ${result.get('comparables_value', 0):.2f}"
        )
        for col in range(6):
            item.setToolTip(col, tooltip)
        
        # Guardar resultado completo
        item.setData(0, self.ENTRY_ROLE, result)
    
    def result_from_item(self, item: Optional[QtWidgets.QTreeWidgetItem]) -> Optional[Dict]:
        """Obtiene el resultado completo desde un item"""
        if item is None:
            return None
        data = item.data(0, self.ENTRY_ROLE)
        if isinstance(data, dict):
            return data
        return None
    
    def _ensure_placeholder(self):
        """Muestra placeholder cuando no hay datos"""
        # Verificar si el placeholder ya existe y es válido
        if self._placeholder_item is not None:
            try:
                # Verificar que el item todavía existe
                index = self.indexOfTopLevelItem(self._placeholder_item)
                if index != -1:
                    return  # Ya existe y es válido
            except RuntimeError:
                # El item fue eliminado, limpiar referencia
                self._placeholder_item = None
            except Exception:
                # Cualquier otro error, limpiar referencia
                self._placeholder_item = None
        
        # Crear nuevo placeholder
        placeholder = QtWidgets.QTreeWidgetItem(["Sin datos disponibles", "", "", "", "", ""])
        font = placeholder.font(0)
        font.setItalic(True)
        placeholder.setFont(0, font)
        placeholder.setFlags(QtCore.Qt.NoItemFlags)
        self.addTopLevelItem(placeholder)
        self._placeholder_item = placeholder
    
    def _remove_placeholder(self):
        """Remueve el placeholder"""
        if self._placeholder_item is None:
            return
        
        try:
            # Verificar que el item todavía existe antes de acceder a él
            index = self.indexOfTopLevelItem(self._placeholder_item)
            if index != -1:
                self.takeTopLevelItem(index)
        except RuntimeError:
            # El item ya fue eliminado, solo limpiar la referencia
            pass
        except Exception:
            # Cualquier otro error, solo limpiar la referencia
            pass
        finally:
            self._placeholder_item = None


class DetailDialog(QtWidgets.QDialog):
    """Diálogo para mostrar detalles completos de una valoración"""
    
    def __init__(self, result: Dict, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalles - {result.get('symbol', 'N/A')}")
        self.resize(600, 500)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Información principal
        main_info = QtWidgets.QGroupBox("Información Principal", self)
        main_layout = QtWidgets.QFormLayout(main_info)
        
        symbol = result.get("symbol", "")
        buy = result.get("buy", False)
        decision_text = "✅ COMPRAR" if buy else "❌ NO COMPRAR"
        decision_color = QtGui.QColor(0, 150, 0) if buy else QtGui.QColor(200, 0, 0)
        
        symbol_label = QtWidgets.QLabel(symbol)
        font = symbol_label.font()
        font.setPointSize(14)
        font.setBold(True)
        symbol_label.setFont(font)
        main_layout.addRow("Símbolo:", symbol_label)
        
        decision_label = QtWidgets.QLabel(decision_text)
        decision_label.setStyleSheet(f"color: {decision_color.name()}; font-weight: bold;")
        main_layout.addRow("Decisión:", decision_label)
        
        main_layout.addRow("Precio Actual:", QtWidgets.QLabel(f"${result.get('current_price', 0):.2f}"))
        main_layout.addRow("Valor Intrínseco:", QtWidgets.QLabel(f"${result.get('intrinsic_value', 0):.2f}"))
        main_layout.addRow("Valoración:", QtWidgets.QLabel(f"{result.get('valuation_percentage', 0):+.2f}%"))
        main_layout.addRow("Status:", QtWidgets.QLabel(result.get("status", "")))
        
        layout.addWidget(main_info)
        
        # Métricas DCF
        dcf_info = QtWidgets.QGroupBox("Escenarios DCF", self)
        dcf_layout = QtWidgets.QFormLayout(dcf_info)
        
        dcf_layout.addRow("Pesimista:", QtWidgets.QLabel(f"${result.get('dcf_pessimistic', 0):.2f}"))
        dcf_layout.addRow("Base:", QtWidgets.QLabel(f"${result.get('dcf_base', 0):.2f}"))
        dcf_layout.addRow("Optimista:", QtWidgets.QLabel(f"${result.get('dcf_optimistic', 0):.2f}"))
        dcf_layout.addRow("Comparables:", QtWidgets.QLabel(f"${result.get('comparables_value', 0):.2f}"))
        
        layout.addWidget(dcf_info)
        
        # Información adicional
        extra_info = QtWidgets.QGroupBox("Información Adicional", self)
        extra_layout = QtWidgets.QFormLayout(extra_info)
        
        extra_layout.addRow("Surprise EPS:", QtWidgets.QLabel(f"{result.get('surprise_eps', 0):+.2f}"))
        extra_layout.addRow("Razón:", QtWidgets.QLabel(result.get("decision_reason", "")))
        
        timestamp = result.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                timestamp_str = timestamp
            extra_layout.addRow("Timestamp:", QtWidgets.QLabel(timestamp_str))
        
        layout.addWidget(extra_info)
        
        # Botones
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

