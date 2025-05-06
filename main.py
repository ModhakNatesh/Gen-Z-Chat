import sys
import os
import shutil
import json
from datetime import datetime
import google.generativeai as genai
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QPushButton, 
                            QScrollArea, QLabel, QFrame, QDialog,
                            QMessageBox, QFileDialog, QStackedWidget, 
                            QProgressBar, QSizePolicy, QComboBox, QFileDialog,  QTextEdit, QToolTip)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QPropertyAnimation, QEasingCurve, QRect, QSize, QTimer, QPoint, QEvent
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QPixmap, QFontDatabase, QCursor
import requests
from PIL import Image
import base64
import random
import urllib.parse
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration file path
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".gemini_chatbot_config.json")

# Custom emoji constants
EMOJI_LIST = ["✨", "🔥", "💯", "👾", "🚀", "💅", "🤙", "🌈", "😎", "🥶", "👀", "💁‍♀️", "🤌"]

class SlidingStackedWidget(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.m_direction = Qt.Orientation.Horizontal
        self.m_speed = 500
        self.m_animationType = QEasingCurve.Type.OutCubic
        self.m_wrap = False
        self.m_active = False
        self.m_currentIndex = 0
        self.m_next = 0

    def setDirection(self, direction):
        self.m_direction = direction

    def slideIn(self, index):
        if self.m_active:
            return
            
        self.m_active = True
        
        width = self.frameRect().width()
        height = self.frameRect().height()
        
        next_widget = self.widget(index)
        
        if self.m_direction == Qt.Orientation.Horizontal:
            offset = width
        else:
            offset = height
            
        # Position next widget outside the stack widget
        next_widget.setGeometry(0, 0, width, height)
        
        # Move next widget into position with animation
        self.m_next = index
        
        curr_widget = self.widget(self.currentIndex())
        
        # Prepare animations
        self.anim_group_out = QPropertyAnimation(curr_widget, b"geometry")
        self.anim_group_out.setDuration(self.m_speed)
        self.anim_group_out.setEasingCurve(self.m_animationType)
        self.anim_group_out.setStartValue(QRect(0, 0, width, height))
        self.anim_group_out.setEndValue(QRect(-width, 0, width, height))
        
        self.anim_group_in = QPropertyAnimation(next_widget, b"geometry")
        self.anim_group_in.setDuration(self.m_speed)
        self.anim_group_in.setEasingCurve(self.m_animationType)
        self.anim_group_in.setStartValue(QRect(width, 0, width, height))
        self.anim_group_in.setEndValue(QRect(0, 0, width, height))
        
        self.anim_group_out.finished.connect(self.animation_done)
        
        # Start animations
        self.anim_group_out.start()
        self.anim_group_in.start()
        
    def animation_done(self):
        self.setCurrentIndex(self.m_next)
        self.m_active = False

class ApiKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gemini API Key")
        self.setFixedSize(450, 200)
        
        layout = QVBoxLayout()
        
        # Add some Gen Z flair to the dialog
        title_label = QLabel("✨ Drop Your API Key Here ✨")
        title_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: #A370F7;
            margin-bottom: 10px;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # API Key message
        info_label = QLabel("You'll need a Gemini API Key to vibe with this app.\nGrab your free key from https://ai.google.dev/ — it's giving main character energy!")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #E0E0E0; font-size: 14px;")
        layout.addWidget(info_label)
        
        # API Key input
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Paste your Gemini API Key here")
        self.api_key_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #A370F7;
                border-radius: 18px;
                padding: 12px 15px;
                background-color: #2D2D30;
                color: white;
                font-size: 14px;
                margin: 10px 0px;
            }
        """)
        layout.addWidget(self.api_key_input)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("Nah, I'm Good")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #3B3B3D;
                border-radius: 15px;
                padding: 10px 15px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4E4E50;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        
        self.save_button = QPushButton("Let's Gooo!")
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #A370F7;
                border-radius: 15px;
                padding: 10px 15px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8A5CF5;
            }
        """)
        self.save_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def get_api_key(self):
        return self.api_key_input.text().strip()

class MessageWorker(QThread):
    response_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, model, message, chat_history, image_path=None):
        super().__init__()
        self.model = model
        self.message = message
        self.chat_history = chat_history
        self.image_path = image_path
        
    def run(self):
        try:
            # Create the prompt by including chat history context
            history_text = []
            for msg in self.chat_history:
                role = "user" if msg["role"] == "user" else "model"
                
                # Skip images in history for simplicity
                history_text.append({"role": role, "parts": [msg["content"]]})
            
            # Add the current message with image if provided
            if self.image_path:
                try:
                    # For Gemini, we need to use the specific GenerativeModel.generate_content format
                    # First, add previous history without the image
                    
                    # Then create a new content array with the image
                    content_parts = []
                    
                    # Add text part if there's a message
                    if self.message:
                        content_parts.append({"text": self.message})
                    
                    # Add image part using the proper format
                    with open(self.image_path, "rb") as f:
                        image_bytes = f.read()
                    
                    content_parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode('utf-8')
                        }
                    })
                    
                    # Make API call with image
                    response = self.model.generate_content(
                        content_parts,
                        generation_config={
                            "temperature": 0.9,
                            "max_output_tokens": 1000,
                        }
                    )
                except Exception as e:
                    self.error_occurred.emit(f"Failed to process image: {str(e)}")
                    return
            else:
                # Normal text message with history
                response = self.model.generate_content(
                    history_text,
                    generation_config={
                        "temperature": 0.9,
                        "max_output_tokens": 1000,
                    }
                )
            
            # Process the response
            response_dict = {
                "text": response.text,
                "images": []  # Will contain URLs if images are generated
            }
            
            self.response_ready.emit(response_dict)
        except Exception as e:
            self.error_occurred.emit(str(e))

class AnimatedLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.duration = 1000
        
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(self.duration)
        self.animation.setStartValue(QRect(0, 0, 100, 30))
        self.animation.setEndValue(QRect(0, 0, 100, 30))
        self.animation.setEasingCurve(QEasingCurve.Type.OutBounce)
        self.animation.start()

class ChatBubble(QFrame):
    def __init__(self, content, is_user=True, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        
        # Check if content is a dict (new format) or string (old format)
        if isinstance(content, dict):
            self.text = content.get("text", "")
            self.images = content.get("images", [])
        else:
            self.text = content
            self.images = []
            
        self.init_ui()
        
    def init_ui(self):
        # Import Qt at the beginning of the method to ensure it's available
        from PyQt6.QtCore import Qt
        
        # Reset any existing layout and margins
        self.setContentsMargins(0, 0, 0, 0)
        
        # Create main layout with proper spacing
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 10, 0, 10)  # Increased vertical padding
        main_layout.setSpacing(0)
        
        # Create bubble container
        bubble_container = QWidget()
        bubble_layout = QVBoxLayout(bubble_container)
        bubble_layout.setSpacing(6)  # Slightly increased spacing
        
        # Message content
        message_container = QWidget()
        message_layout = QVBoxLayout(message_container)
        message_layout.setContentsMargins(18, 16, 18, 16)  # Increased padding
        
        # For bot messages, use QTextEdit instead of QLabel to enable better text selection
        if not self.is_user:
            self.message = QTextEdit()
            self.message.setReadOnly(True)
            self.message.setHtml(self.text)
            self.message.setStyleSheet("""
                color: white; 
                font-size: 15px;  /* Increased font size */
                line-height: 145%;  /* Added line spacing */
                background: transparent;
                border: none;
                padding: 2px;
            """)
            
            # Make the text edit automatically resize to fit content
            self.message.document().documentLayout().documentSizeChanged.connect(
                lambda: self.adjust_text_size()
            )
            
            # Set text edit to automatically expand
            self.message.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.message.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
            )
            
            # Create copy button for bot messages
            copy_button = QPushButton("Copy")
            copy_button.setStyleSheet("""
                background-color: #5D4E9E;
                color: white;
                border-radius: 8px;
                padding: 6px 12px;  /* Larger padding */
                font-size: 12px;
                margin-top: 8px;
                font-weight: 500;
            """)
            copy_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            copy_button.clicked.connect(lambda: self.copy_text_to_clipboard())
            
            # Add copy button to message layout
            button_container = QWidget()
            button_layout = QHBoxLayout(button_container)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.addStretch()
            button_layout.addWidget(copy_button)
            
            message_layout.addWidget(self.message)
            message_layout.addWidget(button_container)
        else:
            # User message still uses QLabel but with improved styling
            self.message = QLabel(self.text)
            self.message.setWordWrap(True)
            
            self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.message.setStyleSheet("""
                color: white; 
                font-size: 15px;  /* Increased font size */
                line-height: 145%;  /* Added line spacing */
                background: transparent;
                padding: 2px;
            """)
            
            message_layout.addWidget(self.message)
        
        # Add images if any (commented out in original code)
        # Image handling code would go here
        
        # Time stamp with emoji for Gen Z flair
        random_emoji = random.choice(EMOJI_LIST)
        time_str = datetime.now().strftime("%H:%M")
        time_label = QLabel(f"{time_str} {random_emoji}")
        time_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px;")
        
        # Apply styles based on sender
        if self.is_user:
            # User message styling with improved gradient
            gradient = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #A575FF, stop:1 #9F6EFF)"
            message_container.setStyleSheet(f"""
                background: {gradient};
                border-radius: 20px 8px 20px 20px;  /* Increased border-radius */
                color: white;
            """)
            
            # Add time label to right side of bubble
            time_container = QWidget()
            time_layout = QHBoxLayout(time_container)
            time_layout.setContentsMargins(4, 0, 10, 0)  # Increased right margin
            time_layout.addStretch()
            time_layout.addWidget(time_label)
            
            bubble_layout.addWidget(message_container)
            bubble_layout.addWidget(time_container)
            
            # Right-align the bubble
            main_layout.addStretch(1)
            main_layout.addWidget(bubble_container)
            main_layout.addSpacing(20)  # Increased right margin
        else:
            # Bot message styling with improved gradient
            gradient = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #363636, stop:1 #2D2D30)"
            message_container.setStyleSheet(f"""
                background: {gradient};
                border-radius: 8px 20px 20px 20px;  /* Increased border-radius */
                color: white;
            """)
            
            # Add time label to left side of bubble
            time_container = QWidget()
            time_layout = QHBoxLayout(time_container)
            time_layout.setContentsMargins(10, 0, 4, 0)  # Increased left margin
            time_layout.addWidget(time_label)
            time_layout.addStretch()
            
            bubble_layout.addWidget(message_container)
            bubble_layout.addWidget(time_container)
            
            # Left-align the bubble
            main_layout.addSpacing(20)  # Increased left margin
            main_layout.addWidget(bubble_container)
            main_layout.addStretch(1)
        
        # Set the frame to be transparent
        self.setStyleSheet("background: transparent; border: none;")
        
        # Adjust sizing with improved width calculations
        parent_width = self.parent().width() if self.parent() else 1200  # Increased default width
        max_width = int(parent_width * 0.85)  # Adjusted to 85% of parent width for better balance
        message_container.setMaximumWidth(max_width)
        
        # For bot messages, adjust sizing for dynamic content
        if not self.is_user:
            # Set reasonable minimum height
            self.message.setMinimumHeight(30)  # Reduced minimum height to better fit smaller responses
            # Call initial resize adjustment
            self.adjust_text_size()
        
        # Create size policies that work across Qt versions
        expanding_policy = QSizePolicy()
        expanding_policy.setHorizontalStretch(1)
        expanding_policy.setHorizontalPolicy(QSizePolicy.Expanding if not hasattr(QSizePolicy, 'Policy') else QSizePolicy.Policy.Expanding)
        expanding_policy.setVerticalPolicy(QSizePolicy.Minimum if not hasattr(QSizePolicy, 'Policy') else QSizePolicy.Policy.Minimum)
        
        preferred_policy = QSizePolicy()
        preferred_policy.setHorizontalPolicy(QSizePolicy.Preferred if not hasattr(QSizePolicy, 'Policy') else QSizePolicy.Policy.Preferred)
        preferred_policy.setVerticalPolicy(QSizePolicy.Minimum if not hasattr(QSizePolicy, 'Policy') else QSizePolicy.Policy.Minimum)
        
        # Apply size policies
        self.setSizePolicy(expanding_policy)
        bubble_container.setSizePolicy(preferred_policy)
        message_container.setSizePolicy(preferred_policy)
        
    def copy_text_to_clipboard(self):
        """Copy the plain text content to clipboard with improved feedback"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.message.toPlainText())
        
        # Show a temporary tooltip with improved position
        QToolTip.showText(self.sender().mapToGlobal(QPoint(0, -30)), "Copied to clipboard!", self)
        
        # Change the button text temporarily with improved visual feedback
        sender = self.sender()
        original_text = sender.text()
        sender.setText("✓ Copied!")
        
        # Save the original style and apply a success style
        original_style = sender.styleSheet()
        sender.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 12px;
            margin-top: 8px;
            font-weight: 500;
        """)
        
        # Reset button after a short delay
        QTimer.singleShot(1500, lambda: self.reset_button(sender, original_text, original_style))
    
    def reset_button(self, button, original_text, original_style):
        """Reset button to original state with animation effect"""
        button.setText(original_text)
        button.setStyleSheet(original_style)
    
    def adjust_text_size(self):
        """Dynamically adjust the height of the QTextEdit based on its content with improved calculations"""
        # Calculate the document height
        document = self.message.document()
        document_height = document.size().height()
        
        # Add padding proportional to content size
        padding = 24  # Base padding
        new_height = document_height + padding
        
        # Set reasonable constraints
        min_height = 40  # Adjusted minimum height
        max_height = 600  # More reasonable maximum (about 25-30 lines of text)
        
        # Apply height constraints
        if new_height < min_height:
            new_height = min_height
        elif new_height > max_height:
            new_height = max_height
            # Enable scrollbar if content exceeds max height
            self.message.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            # Disable scrollbar for content that fits
            self.message.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Apply the new height
        self.message.setFixedHeight(int(new_height))
        
        # Force layout update
        self.message.updateGeometry()
        if self.parent():
            self.parent().updateGeometry()


class ChatInput(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        # Import Qt at the beginning of the method
        from PyQt6.QtCore import Qt
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)  # Increased padding
        
        # Create a container for the input area with a background
        input_bg = QWidget()
        input_bg.setStyleSheet("""
            background-color: #272729;
            border-radius: 24px;
            padding: 4px;
        """)
        input_bg_layout = QHBoxLayout(input_bg)
        input_bg_layout.setContentsMargins(6, 6, 6, 6)
        
        # Create a text input that can expand vertically with improved appearance
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Message GenZ Chat Bot...")
        
        # Improved styling for the input text
        self.text_input.setStyleSheet("""
            QTextEdit {
                background-color: #2D2D30;
                border-radius: 20px;
                padding: 14px 18px;
                color: white;
                font-size: 15px;
                line-height: 145%;
                border: 1px solid #3D3D42;
            }
            QTextEdit:focus {
                border: 1px solid #5D4E9E;
            }
        """)
        
        # Improved input size constraints for better usability
        self.text_input.setMinimumHeight(50)
        self.text_input.setMaximumHeight(200)  # Allow taller messages
        
        # Create send button with improved Gen Z styling
        self.send_button = QPushButton("Send")
        self.send_button.setFixedSize(QSize(90, 44))  # Fixed dimensions for consistency
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #9F6EFF;
                color: white;
                border-radius: 18px;
                padding: 10px 20px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8A5CE6;
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #7D52D7;
            }
        """)
        
        # Add text input and button to container
        input_bg_layout.addWidget(self.text_input, 1)
        input_bg_layout.addWidget(self.send_button)
        
        # Add the input container to the main layout
        layout.addWidget(input_bg)
        
        # Connect signals
        self.send_button.clicked.connect(self.send_message)
        self.text_input.installEventFilter(self)
        
        # Make the text input respond to Enter key while allowing Shift+Enter for newlines
        self.text_input.textChanged.connect(self.adjust_input_height)
        
    def eventFilter(self, obj, event):
        # Import Qt for event handling
        from PyQt6.QtCore import Qt, QEvent
        
        if obj is self.text_input and event.type() == QEvent.Type.KeyPress:
            # Send on Enter, new line on Shift+Enter
            if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.send_message()
                return True
            # Also handle Ctrl+Enter as alternative send shortcut
            elif event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)
    
    def adjust_input_height(self):
        """Dynamically adjust the height of the input field based on content"""
        document = self.text_input.document()
        document_height = document.size().height()
        
        # Calculate new height with padding
        new_height = document_height + 28  # Add padding
        
        # Apply constraints
        min_height = 50
        max_height = 200
        
        if new_height < min_height:
            self.text_input.setFixedHeight(min_height)
        elif new_height > max_height:
            self.text_input.setFixedHeight(max_height)
        else:
            self.text_input.setFixedHeight(int(new_height))
        
        # Update widget layout
        self.text_input.updateGeometry()
        self.updateGeometry()
        
    def send_message(self):
        text = self.text_input.toPlainText().strip()
        if text:
            # Emit a signal or call a method on parent to send the message
            if hasattr(self.parent(), 'send_user_message'):
                self.parent().send_user_message(text)
            self.text_input.clear()
            
    def get_text(self):
        return self.text_input.toPlainText()
        
    def clear(self):
        self.text_input.clear()
        

class LoadingIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        
        self.label = QLabel("Gemini is cooking up something fire...")
        self.label.setStyleSheet("color: #A370F7; font-style: italic;")
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(5)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 2px;
                background-color: #333;
            }
            
            QProgressBar::chunk {
                background-color: #A370F7;
                border-radius: 2px;
            }
        """)
        
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        
        self.setMaximumHeight(50)
        self.setStyleSheet("background-color: rgba(45, 45, 48, 0.7); border-radius: 10px; padding: 5px;")

class EmojiSelector(QFrame):
    emoji_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            background-color: #2D2D30;
            border: 1px solid #444;
            border-radius: 10px;
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        for emoji in EMOJI_LIST:
            btn = QPushButton(emoji)
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #333;
                    border-radius: 16px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #444;
                }
            """)
            btn.clicked.connect(lambda _, e=emoji: self.emoji_selected.emit(e))
            layout.addWidget(btn)
        
        self.setMaximumHeight(45)

class ThemeSelector(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QComboBox {
                border: 1px solid #444;
                border-radius: 10px;
                padding: 5px 10px;
                background-color: #2D2D30;
                color: white;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: url('down_arrow.png');
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #444;
                selection-background-color: #A370F7;
                background-color: #2D2D30;
                color: white;
            }
        """)
        
        # Add theme options
        self.addItem("💜 Purple Vibe")
        self.addItem("💙 Blue Wave")
        self.addItem("💚 Green Scene")
        self.addItem("🖤 Dark Mode")
        self.addItem("🌈 Rainbow")

class GenZChatbot(QMainWindow):
    def __init__(self):
        super().__init__()
        self.chat_history = []
        self.model = None
        self.current_image = None
        self.init_ui()
        self.load_config()
        
    def init_ui(self):
        self.setWindowTitle("Vibe Check ✨ GenZ Gemini Chatbot")
        self.setGeometry(100, 100, 950, 700)
        
        # Load custom fonts
        font_id = QFontDatabase.addApplicationFont("./fonts/Poppins-Regular.ttf")
        if font_id != -1:
            self.app_font = QFont("Poppins", 10)
            QApplication.setFont(self.app_font)
        else:
            self.app_font = QFont("Segoe UI", 10)
            QApplication.setFont(self.app_font)
        
        # Set dark theme
        self.set_dark_theme()
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create stacked widget for multiple screens
        self.stacked_widget = SlidingStackedWidget()
        
        # Create main chat page
        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        
        # Enhanced header area with gradient and glow effect
        header_widget = QWidget()
        header_widget.setObjectName("headerWidget")
        header_widget.setStyleSheet("""
            #headerWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8A2BE2, stop:0.5 #9A45F0, stop:1 #A370F7);
                border-bottom: 1px solid #8A5CF5;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(18, 12, 18, 12)
        
        # App logo and title with animated effect
        title_layout = QHBoxLayout()
        app_logo = QLabel("🤖")
        app_logo.setStyleSheet("font-size: 30px; margin-right: 8px;")
        
        app_title = QLabel("GenZ Gemini")
        app_title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        
        title_layout.addWidget(app_logo)
        title_layout.addWidget(app_title)
        
        # Theme selector with improved styling
        self.theme_selector = ThemeSelector()
        self.theme_selector.setStyleSheet("""
            QComboBox {
                background-color: rgba(255, 255, 255, 0.15);
                border-radius: 18px;
                padding: 6px 16px;
                color: white;
                min-width: 130px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2D2D30;
                border: 1px solid #555;
                border-radius: 8px;
                selection-background-color: #A370F7;
            }
        """)
        self.theme_selector.currentIndexChanged.connect(self.change_theme)
        
        # Button layout for header with improved styling
        header_buttons_layout = QHBoxLayout()
        
        self.image_mode_button = QPushButton("🖼️ Image Mode")
        self.image_mode_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 18px;
                padding: 10px 18px;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.25);
            }
        """)
        self.image_mode_button.clicked.connect(self.toggle_image_mode)
        
        self.api_key_button = QPushButton("🔑 API Key")
        self.api_key_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 18px;
                padding: 10px 18px;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.25);
            }
        """)
        self.api_key_button.clicked.connect(self.change_api_key)
        
        self.clear_button = QPushButton("🧹 Clear")
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 18px;
                padding: 10px 18px;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.25);
            }
        """)
        self.clear_button.clicked.connect(self.clear_chat)
        
        header_buttons_layout.addWidget(self.image_mode_button)
        header_buttons_layout.addSpacing(6)
        header_buttons_layout.addWidget(self.api_key_button)
        header_buttons_layout.addSpacing(6)
        header_buttons_layout.addWidget(self.clear_button)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.theme_selector)
        header_layout.addSpacing(18)
        header_layout.addLayout(header_buttons_layout)
        
        # Enhanced chat area with improved styling
        self.chat_area = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_area)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(30)  # Increased spacing for better readability
        # self.chat_layout.setContentsMargins(40, 40, 40, 40)  # Increased margins
        
        # Make the chat area expand properly
        self.chat_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Scroll area for chat with enhanced styling
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.chat_area)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1A1A1D;
            }
            QScrollBar:vertical {
                border: none;
                background: #2D2D30;
                width: 16px;
                margin: 0px;
                border-radius: 8px;
            }
            QScrollBar::handle:vertical {
                background: #555;
                min-height: 35px;
                border-radius: 8px;
            }
            QScrollBar::handle:vertical:hover {
                background: #777;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        # Emoji selector with improved styling
        self.emoji_selector = EmojiSelector()
        self.emoji_selector.emoji_selected.connect(self.insert_emoji)
        self.emoji_selector.setVisible(False)
        self.emoji_selector.setStyleSheet("""
            QWidget {
                background-color: #2D2D30;
                border: 1px solid #555;
                border-radius: 16px;
            }
            QPushButton {
                font-size: 18px;
                padding: 8px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(163, 112, 247, 0.2);
            }
        """)
        
        # Enhanced input area with more Gen Z style
        input_widget = QWidget()
        input_widget.setObjectName("inputWidget")
        input_widget.setStyleSheet("""
            #inputWidget {
                background-color: #222224;
                border-top: 1px solid #444;
                padding: 18px;
            }
        """)
        input_layout = QVBoxLayout(input_widget)
        input_layout.setContentsMargins(25, 18, 25, 18)
        
        # Input controls with better spacing and styling
        input_controls = QHBoxLayout()
        input_controls.setSpacing(16)  # Increase spacing between elements
        
        # Image upload button with enhanced styling
        self.image_upload_btn = QPushButton("📷")
        self.image_upload_btn.setToolTip("Upload an image")
        self.image_upload_btn.setFixedSize(50, 50)
        self.image_upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B3B3D;
                border-radius: 25px;
                font-size: 24px;
                border: 1px solid #555;
            }
            QPushButton:hover {
                background-color: #4E4E50;
            }
            QPushButton:pressed {
                background-color: #555558;
            }
        """)
        self.image_upload_btn.clicked.connect(self.upload_image)
        
        # Emoji button with enhanced styling
        self.emoji_btn = QPushButton("😀")
        self.emoji_btn.setToolTip("Add emoji")
        self.emoji_btn.setFixedSize(50, 50)
        self.emoji_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B3B3D;
                border-radius: 25px;
                font-size: 24px;
                border: 1px solid #555;
            }
            QPushButton:hover {
                background-color: #4E4E50;
            }
            QPushButton:pressed {
                background-color: #555558;
            }
        """)
        self.emoji_btn.clicked.connect(self.toggle_emoji_selector)
        
        # Enhanced text input with improved styling
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Drop your thoughts here... fr fr")
        self.message_input.setMinimumHeight(50)  # Taller input field
        self.message_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #444;
                border-radius: 25px;
                padding: 10px 22px;
                background-color: #2D2D30;
                color: white;
                font-size: 16px;
            }
            QLineEdit:focus {
                border: 2px solid #A370F7;
                background-color: #333336;
            }
        """)
        self.message_input.returnPressed.connect(self.send_message)
        
        # Enhanced send button with improved style
        self.send_button = QPushButton()
        send_icon = QIcon.fromTheme("document-send")
        self.send_button.setIcon(send_icon)
        self.send_button.setIconSize(QSize(28, 28))  # Larger icon
        self.send_button.setFixedSize(50, 50)
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #A370F7;
                border-radius: 25px;
            }
            QPushButton:hover {
                background-color: #8A5CF5;
            }
            QPushButton:pressed {
                background-color: #7A4CE5;
            }
        """)
        self.send_button.clicked.connect(self.send_message)
        
        input_controls.addWidget(self.image_upload_btn)
        input_controls.addWidget(self.emoji_btn)
        input_controls.addWidget(self.message_input)
        input_controls.addWidget(self.send_button)
        
        # Enhanced image preview with improved styling
        self.image_preview = QLabel()
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMaximumHeight(220)  # Taller preview
        self.image_preview.setStyleSheet("""
            QLabel {
                margin-bottom: 18px;
                border: 2px solid #555;
                border-radius: 14px;
                padding: 8px;
                background-color: #222224;
            }
        """)
        self.image_preview.setVisible(False)
        self.image_preview.resizeEvent = self.update_clear_button_position
        
        # Enhanced clear image button
        self.clear_image_btn = QPushButton("❌")
        self.clear_image_btn.setFixedSize(32, 32)
        self.clear_image_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(40, 40, 40, 0.85);
                border-radius: 16px;
                color: white;
                font-weight: bold;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            QPushButton:hover {
                background-color: rgba(70, 70, 70, 0.95);
            }
        """)
        self.clear_image_btn.clicked.connect(self.clear_image)
        self.clear_image_btn.setVisible(False)
        
        # Image preview layout with padding
        image_preview_layout = QHBoxLayout()
        image_preview_layout.setContentsMargins(20, 10, 20, 10)
        image_preview_layout.addStretch()
        image_preview_layout.addWidget(self.image_preview)
        image_preview_layout.addStretch()
        
        # Add emoji selector and input controls
        input_layout.addWidget(self.emoji_selector)
        input_layout.addLayout(image_preview_layout)
        input_layout.addLayout(input_controls)
        
        # Image mode page with enhanced styling
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        
        # Enhanced header for image page
        image_header = QWidget()
        image_header.setObjectName("headerWidget")
        image_header.setStyleSheet("""
            #headerWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8A2BE2, stop:0.5 #9A45F0, stop:1 #A370F7);
                border-bottom: 1px solid #8A5CF5;
            }
        """)
        
        image_header_layout = QHBoxLayout(image_header)
        image_header_layout.setContentsMargins(18, 12, 18, 12)
        
        # Enhanced back button
        back_button = QPushButton("← Back to Chat")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 18px;
                padding: 10px 18px;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.4);
            }
        """)
        back_button.clicked.connect(lambda: self.stacked_widget.slideIn(0))
        
        # Enhanced image title
        image_title = QLabel("✨ Image Generation ✨")
        image_title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        
        image_header_layout.addWidget(back_button)
        image_header_layout.addStretch()
        image_header_layout.addWidget(image_title)
        image_header_layout.addStretch()
        
        # Enhanced image generation area
        image_generation_widget = QWidget()
        image_generation_layout = QVBoxLayout(image_generation_widget)
        image_generation_layout.setContentsMargins(40, 40, 40, 40)
        
        # Enhanced prompt input for image generation
        prompt_label = QLabel("What image should I create for you?")
        prompt_label.setStyleSheet("color: white; font-size: 20px; margin-top: 20px; font-weight: bold;")
        prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.image_prompt_input = QLineEdit()
        self.image_prompt_input.setPlaceholderText("Describe the image you want...")
        self.image_prompt_input.setMinimumHeight(50)
        self.image_prompt_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #444;
                border-radius: 25px;
                padding: 10px 25px;
                background-color: #2D2D30;
                color: white;
                font-size: 16px;
                margin: 20px 60px;
            }
            QLineEdit:focus {
                border: 2px solid #A370F7;
                background-color: #333336;
            }
        """)
        
        # Enhanced generate button
        generate_button = QPushButton("Generate Image 🎨")
        generate_button.setStyleSheet("""
            QPushButton {
                background-color: #A370F7;
                border-radius: 25px;
                padding: 16px;
                color: white;
                font-weight: bold;
                font-size: 18px;
                margin: 25px 120px;
            }
            QPushButton:hover {
                background-color: #8A5CF5;
            }
            QPushButton:pressed {
                background-color: #7A4CE5;
            }
        """)
        generate_button.clicked.connect(self.generate_image)
        
        # Enhanced image result area
        self.image_result_label = QLabel("Your generated image will appear here")
        self.image_result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_result_label.setStyleSheet("""
            color: #999;
            font-style: italic;
            background-color: #1D1D1F;
            border: 2px solid #444;
            border-radius: 20px;
            padding: 50px;
            margin: 25px 50px;
            font-size: 16px;
        """)
        self.image_result_label.setMinimumHeight(400)
        self.image_result_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, 
            QSizePolicy.Policy.Expanding
        )
        
        image_generation_layout.addWidget(prompt_label)
        image_generation_layout.addWidget(self.image_prompt_input)
        image_generation_layout.addWidget(generate_button)
        image_generation_layout.addWidget(self.image_result_label)
        image_generation_layout.addStretch()
        
        # Add widgets to image page
        image_layout.addWidget(image_header)
        image_layout.addWidget(image_generation_widget)
        
        # Add pages to stacked widget
        self.stacked_widget.addWidget(chat_page)
        self.stacked_widget.addWidget(image_page)
        
        # Add components to chat page layout
        chat_layout.addWidget(header_widget)
        chat_layout.addWidget(self.scroll_area)
        chat_layout.addWidget(input_widget)
        
        # Set proper size policies
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        input_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # Add stacked widget to main layout
        main_layout.addWidget(self.stacked_widget)
        
        self.setCentralWidget(main_widget)
        
        # Set position for clear image button (overlay on preview)
        self.clear_image_btn.setParent(self.image_preview)
        self.clear_image_btn.move(10, 10)  # Moved slightly away from edge
        
        # New feature: Add animated dots to indicate typing
        self.typing_indicator = QLabel("Gemini is thinking...")
        self.typing_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.typing_indicator.setStyleSheet("""
            color: #A370F7;
            font-style: italic;
            background-color: rgba(30, 30, 32, 0.7);
            border-radius: 15px;
            padding: 10px 20px;
            margin: 0px 40px;
            font-size: 14px;
        """)
        self.typing_indicator.setVisible(False)
        self.chat_layout.addWidget(self.typing_indicator)
        
        # Add some placeholder animation for the typing indicator
        self.typing_timer = QTimer()
        self.typing_timer.timeout.connect(self.update_typing_animation)
        self.typing_dots = 0
        
        # Add some subtle particle effects in the background
        # self.setup_particle_effects()
        
    def update_typing_animation(self):
        """
        Update the typing animation dots for the Gemini thinking indicator.
        """
        self.typing_dots = (self.typing_dots + 1) % 4
        dots = "." * self.typing_dots
        self.typing_indicator.setText(f"Gemini is thinking{dots}")

    def get_unsplash_image(self, query):
        """Get a free image from Unsplash based on the query with improved error handling"""
        try:
            # Disable SSL warnings for this request only
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # Use a more reliable Unsplash Source API endpoint
            base_url = "https://source.unsplash.com/random?"
            search_url = base_url + urllib.parse.quote(query)
            
            # Make request with SSL verification disabled and proper headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(search_url, verify=False, allow_redirects=True, timeout=15, headers=headers)
            
            if response.status_code == 200:
                # Save to a temporary file
                temp_dir = os.path.join(os.path.expanduser("~"), ".genz_chatbot_temp")
                os.makedirs(temp_dir, exist_ok=True)
                
                # Create a filename based on timestamp
                filename = os.path.join(temp_dir, f"image_{int(datetime.now().timestamp())}.jpg")
                
                with open(filename, 'wb') as f:
                    f.write(response.content)
                
                return filename
            else:
                print(f"Failed to get image: Status code {response.status_code}")
                return None
        except Exception as e:
            print(f"Error getting image: {str(e)}")
            return None

    def resizeEvent(self, event):
        """Handle resize events properly"""
        super().resizeEvent(event)
        
        # Limit maximum width to screen width
        screen_size = QApplication.primaryScreen().size()
        if self.width() > screen_size.width():
            self.resize(screen_size.width(), self.height())
        
        # Update image preview clear button position
        self.update_clear_button_position()
        
        # If we have an image in the result label, make sure it's properly sized
        if hasattr(self, 'image_result_label') and self.image_result_label.pixmap():
            pixmap = self.image_result_label.pixmap()
            max_width = self.image_result_label.width() - 40
            max_height = self.image_result_label.height() - 40
            
            if pixmap.width() > max_width or pixmap.height() > max_height:
                scaled_pixmap = pixmap.scaled(max_width, max_height, Qt.AspectRatioMode.KeepAspectRatio)
                self.image_result_label.setPixmap(scaled_pixmap)
    
    def set_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 33))
        dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 48))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 33))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 48))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(163, 112, 247))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(163, 112, 247))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        
        self.setPalette(dark_palette)

    def update_clear_button_position(self, event=None):
        if hasattr(self, 'clear_image_btn') and self.clear_image_btn.isVisible():
            # Position in top-right corner with some padding
            self.clear_image_btn.move(
                self.image_preview.width() - self.clear_image_btn.width() - 5, 
                5
            )
    
    def change_theme(self, index):
        themes = {
            0: {"primary": "#A370F7", "primary_dark": "#9F6EFF", "accent": "#A370F7"}, # Purple
            1: {"primary": "#1E88E5", "primary_dark": "#1976D2", "accent": "#29B6F6"}, # Blue
            2: {"primary": "#43A047", "primary_dark": "#388E3C", "accent": "#66BB6A"}, # Green
            3: {"primary": "#424242", "primary_dark": "#212121", "accent": "#757575"}, # Dark
            4: {"primary": "#E91E63", "primary_dark": "#C2185B", "accent": "#FF4081"}  # Pink (Rainbow)
        }
        
        selected_theme = themes.get(index, themes[0])
        
        # Update header gradient
        header_style = f"""
            #headerWidget {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                          stop:0 {selected_theme["primary_dark"]}, 
                                          stop:1 {selected_theme["primary"]});
                border-bottom: 1px solid {selected_theme["primary_dark"]};
            }}
        """
        
        # Update buttons
        button_style = f"""
            QPushButton {{
                background-color: {selected_theme["primary"]};
                border-radius: 20px;
            }}
            QPushButton:hover {{
                background-color: {selected_theme["primary_dark"]};
            }}
        """
        
        # Apply styles
        for widget in self.findChildren(QWidget, "headerWidget"):
            widget.setStyleSheet(header_style)
            
        self.send_button.setStyleSheet(button_style)
        
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                if "api_key" in config:
                    self.setup_gemini(config["api_key"])
                else:
                    self.get_api_key()
            except:
                self.get_api_key()
        else:
            self.get_api_key()
    
    def save_config(self, api_key):
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"api_key": api_key}, f)
    
    def get_api_key(self):
        dialog = ApiKeyDialog(self)
        if dialog.exec():
            api_key = dialog.get_api_key()
            if api_key:
                self.save_config(api_key)
                self.setup_gemini(api_key)
            else:
                QMessageBox.warning(self, "API Key Required", 
                                   "An API key is required to use this application.")
                self.get_api_key()
    
    def change_api_key(self):
        dialog = ApiKeyDialog(self)
        if dialog.exec():
            api_key = dialog.get_api_key()
            if api_key:
                self.save_config(api_key)
                self.setup_gemini(api_key)
                QMessageBox.information(self, "Success", "API key updated successfully! Vibes are immaculate!")
    
    def setup_gemini(self, api_key):
        try:
            genai.configure(api_key=api_key)
            
            generation_config = {
                "temperature": 1.0,
                "top_p": 1,
                "top_k": 1,
                "max_output_tokens": 1024,
            }
            
            safety_settings = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ]
            
            try:
                self.model = genai.GenerativeModel(
                    model_name="gemini-1.5-pro-latest",
                    generation_config=generation_config,
                    safety_settings=safety_settings
                )
            except:
                self.model = genai.GenerativeModel(
                    model_name="gemini-1.0-pro",
                    generation_config=generation_config,
                    safety_settings=safety_settings
                )
                
            self.add_system_message("Connected to Gemini! Vibes are immaculate! 💯")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not initialize Gemini: {str(e)}")
    
    def add_message_bubble(self, content, is_user=True):
        bubble = ChatBubble(content, is_user)
        self.chat_layout.addWidget(bubble)
        
        # Auto scroll to bottom
        QApplication.processEvents()
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        
        # Update chat history
        role = "user" if is_user else "assistant"
        
        # Check if content is a dict or string
        if isinstance(content, dict):
            history_entry = {
                "role": role,
                "content": content.get("text", ""),
            }
            
            # Add image path if present
            if content.get("images"):
                history_entry["image"] = content.get("images")[0]
                
            self.chat_history.append(history_entry)
        else:
            self.chat_history.append({"role": role, "content": content})
    
    def add_system_message(self, text):
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("""
            color: #A370F7;
            padding: 8px;
            font-style: italic;
            background-color: rgba(163, 112, 247, 0.1);
            border-radius: 10px;
            margin: 5px 50px;
        """)
        self.chat_layout.addWidget(label)
        
        # Auto scroll to bottom
        QApplication.processEvents()
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
    
    def toggle_emoji_selector(self):
        self.emoji_selector.setVisible(not self.emoji_selector.isVisible())
    
    def insert_emoji(self, emoji):
        current_text = self.message_input.text()
        cursor_pos = self.message_input.cursorPosition()
        new_text = current_text[:cursor_pos] + emoji + current_text[cursor_pos:]
        self.message_input.setText(new_text)
        self.message_input.setCursorPosition(cursor_pos + len(emoji))
        self.emoji_selector.setVisible(False)
        self.message_input.setFocus()
    
    def toggle_image_mode(self):
        self.stacked_widget.slideIn(1)
    
    def upload_image(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg)"
        )
        
        if file_name:
            self.current_image = file_name
            pixmap = QPixmap(file_name)
            
            # Scale the image while maintaining aspect ratio
            max_height = 150
            if pixmap.height() > max_height:
                pixmap = pixmap.scaledToHeight(max_height)
                
            self.image_preview.setPixmap(pixmap)
            self.image_preview.setVisible(True)
            self.clear_image_btn.setVisible(True)
    
    def clear_image(self):
        self.current_image = None
        self.image_preview.clear()
        self.image_preview.setVisible(False)
        self.clear_image_btn.setVisible(False)
    
    def generate_image(self):
        """Generate image using Pollinations API with improved error handling and resizing"""
        prompt = self.image_prompt_input.text().strip()
        if not prompt:
            QMessageBox.warning(self, "Empty Prompt", "Please enter a description for your image.")
            return
            
        # Show loading state
        self.image_result_label.setText("Generating your image... hold tight bestie! ✨")
        self.image_result_label.setStyleSheet("""
            QLabel {
                color: #A370F7;
                font-style: italic;
                background-color: #2D2D30;
                border-radius: 10px;
                padding: 20px;
                margin: 20px;
            }
        """)
        QApplication.processEvents()

        try:
            # Use Pollinations API with direct image generation endpoint
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
            
            # Download the image with proper timeout and headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, timeout=30, verify=False, headers=headers)
            
            if response.status_code == 200:
                # Save to a temporary file
                temp_dir = os.path.join(os.path.expanduser("~"), ".genz_chatbot_temp")
                os.makedirs(temp_dir, exist_ok=True)
                temp_file = os.path.join(temp_dir, f"generated_image_{int(datetime.now().timestamp())}.jpg")
                
                with open(temp_file, 'wb') as f:
                    f.write(response.content)

                # Display the image with better size constraints
                self.display_generated_image(temp_file)
                
                # Store the generated image path
                self.current_image = temp_file
                
                # Add success message
                self.add_system_message("Image generated successfully! Lowkey fire ngl ✨")
            else:
                raise Exception(f"Failed to generate image: Status {response.status_code}")

        except Exception as e:
            error_msg = str(e)
            self.image_result_label.setText(f"Error: {error_msg}")
            self.image_result_label.setStyleSheet("""
                QLabel {
                    color: #FF5555;
                    background-color: #2D2D30;
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px;
                }
            """)
            print(f"Error generating image: {error_msg}")

    def display_generated_image(self, image_path):
        """Helper method to display generated image with proper scaling and download option"""
        pixmap = QPixmap(image_path)
        self.current_image_path = image_path  # Store the path for download functionality
        
        # Calculate available space while respecting window bounds
        available_width = min(512, int(self.width() * 0.7))  # 70% of window width
        available_height = min(512, int(self.height() * 0.6))  # 60% of window height
        
        scaled_pixmap = pixmap.scaled(
            available_width,
            available_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self.image_result_label.setPixmap(scaled_pixmap)
        self.image_result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_result_label.setStyleSheet("""
            QLabel {
                background-color: #2D2D30;
                border-radius: 10px;
                padding: 10px;
                margin: 10px;
            }
        """)
        
        # Add download button if it doesn't exist yet
        if not hasattr(self, 'download_button'):
            self.download_button = QPushButton("Download Image 💾")
            self.download_button.setStyleSheet("""
                QPushButton {
                    background-color: #A370F7;
                    color: white;
                    border-radius: 15px;
                    padding: 8px 16px;
                    font-weight: bold;
                    margin-top: 10px;
                }
                QPushButton:hover {
                    background-color: #8A5CF5;
                }
            """)
            self.download_button.clicked.connect(self.download_image)
            
            # Add download button to the layout
            image_generation_layout = self.image_result_label.parent().layout()
            image_generation_layout.addWidget(self.download_button)
        
        # Show the download button
        self.download_button.setVisible(True)

    def download_image(self):
        """Save the currently displayed image to a user-selected location"""
        if not hasattr(self, 'current_image_path') or not self.current_image_path:
            return
        
        # Get original filename from path
        original_filename = os.path.basename(self.current_image_path)
        
        # Open file dialog for user to choose save location and filename
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image",
            os.path.join(os.path.expanduser("~"), original_filename),
            "Images (*.png *.jpg *.jpeg)"
        )
        
        if file_path:
            try:
                # Copy the image to the selected location
                shutil.copy2(self.current_image_path, file_path)
                
                # Show success message
                QMessageBox.information(
                    self,
                    "Download Complete",
                    f"Image saved successfully to:\n{file_path}"
                )
            except Exception as e:
                # Show error message if download fails
                QMessageBox.critical(
                    self,
                    "Download Failed",
                    f"Failed to save image: {str(e)}"
                )

    def send_message(self):
        message = self.message_input.text().strip()
        if not message:
            return
        
        if not self.model:
            QMessageBox.warning(self, "Not Connected", 
                               "The chatbot is not connected to Gemini API. Please check your API key.")
            return
        
        # Prepare message content (text + optional image)
        message_content = {
            "text": message,
            "images": [self.current_image] if self.current_image else []
        }
        
        # Add user message to chat
        self.add_message_bubble(message_content, is_user=True)
        self.message_input.clear()
        
        # Create and start worker thread
        self.worker = MessageWorker(self.model, message, self.chat_history, self.current_image)
        self.worker.response_ready.connect(self.handle_response)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.start()
        
        # Add loading indicator
        self.loading_indicator = LoadingIndicator()
        self.chat_layout.addWidget(self.loading_indicator)
        
        # Auto scroll to bottom
        QApplication.processEvents()
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        
        # Clear the image after sending
        if self.current_image:
            self.clear_image()
    
    def handle_response(self, response):
        """Handle the bot response with proper text formatting"""
        # Remove loading indicator
        if hasattr(self, 'loading_indicator') and self.loading_indicator:
            self.chat_layout.removeWidget(self.loading_indicator)
            self.loading_indicator.deleteLater()
            self.loading_indicator = None
        
        # Format the response to make it more Gen Z friendly while preserving markdown
        formatted_response = self.format_genz_response(response["text"])
        
        # Convert markdown to HTML for proper display in QTextEdit
        formatted_html = self.markdown_to_html(formatted_response)
        response["text"] = formatted_html
        
        # Add bot message to chat
        self.add_message_bubble(response, is_user=False)

    def format_genz_response(self, text):
        """Add Gen Z style formatting to the response while preserving markdown"""
        import random
        import re
        
        # If the text is highly technical, don't apply GenZ formatting
        if len(text) > 500 or any(code_indicator in text for code_indicator in ["```", "def ", "class ", "<html>"]):
            return text
        
        # Store code blocks and markdown elements to protect them from modification
        protected_elements = []
        
        # Function to store protected elements and replace with placeholders
        def protect_element(match):
            protected_elements.append(match.group(0))
            return f"__PROTECTED_{len(protected_elements)-1}__"
        
        # Protect code blocks
        code_block_pattern = r"```[\s\S]*?```"
        text = re.sub(code_block_pattern, protect_element, text)
        
        # Protect inline code
        inline_code_pattern = r"`[^`]*`"
        text = re.sub(inline_code_pattern, protect_element, text)
        
        # Protect bold and italic text
        bold_pattern = r"\*\*[^*]*\*\*"
        text = re.sub(bold_pattern, protect_element, text)
        italic_pattern = r"\*[^*]*\*"
        text = re.sub(italic_pattern, protect_element, text)
        
        # Now add GenZ slang to the protected text
        gen_z_expressions = [
            " no cap", " fr", " tbh", " lowkey", " highkey", " bet", " vibes", " bruh", 
            " slay", " iconic", " tho", " ngl", " hit different", " is giving", " sheesh"
        ]
        
        # Replace some periods with Gen Z expressions (but not too many)
        sentences = text.split('. ')
        if len(sentences) > 3:
            # Pick 1-2 sentences to modify
            num_to_modify = min(2, len(sentences) // 3)
            indices_to_modify = random.sample(range(len(sentences)), num_to_modify)
            
            for i in indices_to_modify:
                if i < len(sentences) - 1:  # Don't modify the last sentence
                    if random.random() < 0.7:  # 70% chance to add an expression
                        expression = random.choice(gen_z_expressions)
                        sentences[i] = sentences[i] + expression
            
            text = '. '.join(sentences)
        
        # Define emojis
        EMOJI_LIST = ["😂", "💯", "👀", "✨", "🔥", "💅", "🙌", "👑", "🤩", "😭", "💀", "🤌", "🤷‍♀️", "🥺", "👉👈"]
        
        # Randomly add 1-2 emojis
        emoji_count = random.randint(1, 2)
        for _ in range(emoji_count):
            random_emoji = random.choice(EMOJI_LIST)
            # Insert emoji at a random position, preferring the end of sentences
            if '. ' in text:
                parts = text.split('. ')
                part_to_modify = random.randint(0, len(parts) - 1)
                parts[part_to_modify] = parts[part_to_modify] + f" {random_emoji}"
                text = '. '.join(parts)
            else:
                # Just add to the end if no periods
                text = text + f" {random_emoji}"
        
        # Restore protected elements
        for i, element in enumerate(protected_elements):
            text = text.replace(f"__PROTECTED_{i}__", element)
        
        return text

    def markdown_to_html(self, markdown_text):
        """Convert markdown to HTML for proper display in QTextEdit"""
        import re
        
        # Function to process code blocks
        def replace_code_block(match):
            code = match.group(1)
            # Add syntax highlighting classes if needed
            return f'<pre style="background-color: #1E1E1E; padding: 10px; border-radius: 5px; color: #D4D4D4; font-family: monospace;">{code}</pre>'
        
        # Replace code blocks with HTML
        markdown_text = re.sub(r'```([\s\S]*?)```', replace_code_block, markdown_text)
        
        # Replace inline code with HTML
        markdown_text = re.sub(r'`([^`]+)`', r'<code style="background-color: #1E1E1E; padding: 2px 4px; border-radius: 3px; color: #D4D4D4; font-family: monospace;">\1</code>', markdown_text)
        
        # Replace bold text
        markdown_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', markdown_text)
        
        # Replace italic text
        markdown_text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', markdown_text)
        
        # Replace headers (h1, h2, h3)
        markdown_text = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', markdown_text, flags=re.MULTILINE)
        markdown_text = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', markdown_text, flags=re.MULTILINE)
        markdown_text = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', markdown_text, flags=re.MULTILINE)
        
        # Replace bullet points
        markdown_text = re.sub(r'^\* (.*?)$', r'<ul><li>\1</li></ul>', markdown_text, flags=re.MULTILINE)
        # Clean up multiple consecutive ul tags
        markdown_text = re.sub(r'</ul>\s*<ul>', '', markdown_text)
        
        # Replace numbered lists
        markdown_text = re.sub(r'^(\d+)\. (.*?)$', r'<ol start="\1"><li>\2</li></ol>', markdown_text, flags=re.MULTILINE)
        # Clean up multiple consecutive ol tags
        markdown_text = re.sub(r'</ol>\s*<ol start="\d+">', '', markdown_text)
        
        # Replace links
        markdown_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" style="color: #9F6EFF; text-decoration: underline;">\1</a>', markdown_text)
        
        # Replace paragraphs (two newlines)
        markdown_text = re.sub(r'\n\s*\n', r'<br><br>', markdown_text)
        
        # Replace single newlines with <br>
        markdown_text = re.sub(r'\n', r'<br>', markdown_text)
        
        return markdown_text
    
    def handle_error(self, error_message):
        # Remove loading indicator
        if hasattr(self, 'loading_indicator') and self.loading_indicator:
            self.chat_layout.removeWidget(self.loading_indicator)
            self.loading_indicator.deleteLater()
            self.loading_indicator = None
            
        # Add error message
        self.add_system_message(f"Error: {error_message}")
    
    def clear_chat(self):
        # Clear layout with proper resource cleanup
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()  # Hide before deletion to prevent visual artifacts
                widget.deleteLater()
            elif item.layout():
                # Recursively clear nested layouts if any
                self.clear_layout(item.layout())
        
        # Clear chat history
        self.chat_history = []
        
        # Add welcome message
        self.add_system_message("Chat cleared! Fresh vibes only from here! ✨")

    def clear_layout(self, layout):
        """Helper method to recursively clear nested layouts"""
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.hide()
                    widget.deleteLater()
                elif item.layout():
                    self.clear_layout(item.layout())

def main():
    app = QApplication(sys.argv)
    
    # Set application-wide font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    window = GenZChatbot()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()