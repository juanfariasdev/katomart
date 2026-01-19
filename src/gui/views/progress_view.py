from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QProgressBar, QLabel, QPushButton
from PySide6.QtCore import Signal

class ProgressView(QWidget):
    """shows download progress via logging and a progress bar"""
    
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # Progress section
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("Download Progress:"))
        
        self.progress_label = QLabel("0 de 0 aulas")
        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancelar Download")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        progress_layout.addWidget(self.cancel_button)
        
        layout.addLayout(progress_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        layout.addWidget(self.progress_bar)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log_output)
        
        self._total_lessons = 0
        self._completed_lessons = 0

    def _on_cancel_clicked(self) -> None:
        """Emits cancel signal when button is clicked."""
        self.cancel_requested.emit()
        self.cancel_button.setEnabled(False)
        self.log_message("🛑 Cancelamento solicitado...")

    def log_message(self, message: str) -> None:
        """Appends a message to the log output."""
        self.log_output.append(message)

    def set_progress(self, value: int) -> None:
        """Sets the progress bar's value."""
        self.progress_bar.setValue(value)
    
    def set_total_lessons(self, total: int) -> None:
        """Sets the total number of lessons."""
        self._total_lessons = total
        self._completed_lessons = 0
        self.update_progress_label()
    
    def increment_completed_lessons(self) -> None:
        """Increments the completed lessons counter."""
        self._completed_lessons += 1
        self.update_progress_label()
    
    def update_progress_label(self) -> None:
        """Updates the progress label with current counts."""
        self.progress_label.setText(f"{self._completed_lessons} de {self._total_lessons} aulas")
    
    def set_download_active(self, active: bool) -> None:
        """Enables/disables the cancel button based on download state."""
        self.cancel_button.setEnabled(active)
