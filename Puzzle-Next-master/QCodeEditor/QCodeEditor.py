'''
Licensed under the terms of the MIT License
https://github.com/luchko/QCodeEditor
https://github.com/N-I-N-0/Puzzle-Next
@author: Ivan Luchko (luchko.ivan@gmail.com)
@author: Nin0#2257

This module contains the light QPlainTextEdit based QCodeEditor widget which
provides the line numbers bar and the syntax and the current line highlighting.
'''
from PyQt6.QtCore import Qt, QRect, QRegularExpression
from PyQt6.QtWidgets import QWidget, QTextEdit, QPlainTextEdit
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QFont,
    QSyntaxHighlighter,
    QTextFormat,
    QTextCharFormat,
)


class XMLHighlighter(QSyntaxHighlighter):
    '''
    Class for highlighting xml text inherited from QSyntaxHighlighter

    reference:
        http://www.yasinuludag.com/blog/?p=49
    '''

    def __init__(self, parent=None):
        super().__init__(parent)

        self.highlightingRules = []
        self.searchRules = []

        self.xmlElementFormat = QTextCharFormat()
        self.xmlElementFormat.setForeground(QColor("#00ee00"))
        self.highlightingRules.append(
            (QRegularExpression(r"\b[A-Za-z0-9_]+(?=[\s/>])"), self.xmlElementFormat)
        )

        self.xmlAttributeFormat = QTextCharFormat()
        self.xmlAttributeFormat.setFontItalic(True)
        self.xmlAttributeFormat.setForeground(QColor("#d000d0"))
        self.highlightingRules.append(
            (QRegularExpression(r"\b[A-Za-z0-9_]+(?=\=)"), self.xmlAttributeFormat)
        )
        self.highlightingRules.append((QRegularExpression(r"="), self.xmlAttributeFormat))

        self.valueFormat = QTextCharFormat()
        self.valueFormat.setForeground(QColor("#55dddd"))
        self.valueStartExpression = QRegularExpression(r'"')
        self.valueEndExpression = QRegularExpression(r'"(?=[\s></])')

        self.singleLineCommentFormat = QTextCharFormat()
        self.singleLineCommentFormat.setForeground(QColor("#b3b3b3"))
        self.highlightingRules.append(
            (QRegularExpression(r"<!--[^\n]*-->"), self.singleLineCommentFormat)
        )

        self.textFormat = QTextCharFormat()
        self.textFormat.setForeground(QColor("#FFFFFF"))
        self.highlightingRules.append((QRegularExpression(r">(.+)(?=</)"), self.textFormat))

        self.keywordFormat = QTextCharFormat()
        self.keywordFormat.setForeground(QColor("#FFFFFF"))
        keywordPatterns = [r"\?xml\b", r"/>", r">", r"<", r"</"]
        self.highlightingRules += [
            (QRegularExpression(pattern), self.keywordFormat) for pattern in keywordPatterns
        ]

    def setHighlighterColors(self, isDarkMode):
        if isDarkMode:
            self.xmlElementFormat.setForeground(QColor("#00ee00"))
            self.xmlAttributeFormat.setForeground(QColor("#d000d0"))
            self.valueFormat.setForeground(QColor("#55dddd"))
            self.singleLineCommentFormat.setForeground(QColor("#b3b3b3"))
            self.textFormat.setForeground(QColor("#FFFFFF"))
            self.keywordFormat.setForeground(QColor("#FFFFFF"))
        else:
            self.xmlElementFormat.setForeground(QColor("#22863a"))
            self.xmlAttributeFormat.setForeground(QColor("#6f42c1"))
            self.valueFormat.setForeground(QColor("#032f62"))
            self.singleLineCommentFormat.setForeground(QColor("#6a737d"))
            self.textFormat.setForeground(QColor("#24292e"))
            self.keywordFormat.setForeground(QColor("#24292e"))

    @staticmethod
    def _match_start(expression, text, offset=0):
        match = expression.match(text, offset)
        return match.capturedStart() if match.hasMatch() else -1

    @staticmethod
    def _apply_regex_format(expression, text, text_format, apply_format):
        iterator = expression.globalMatch(text)
        while iterator.hasNext():
            match = iterator.next()
            apply_format(match.capturedStart(), match.capturedLength(), text_format)

    def highlightBlock(self, text):
        for expression, text_format in self.highlightingRules:
            self._apply_regex_format(expression, text, text_format, self.setFormat)

        self.setCurrentBlockState(0)
        startIndex = 0
        if self.previousBlockState() != 1:
            startIndex = self._match_start(self.valueStartExpression, text)

        while startIndex >= 0:
            endIndex = self._match_start(self.valueEndExpression, text, startIndex + 1)
            if endIndex == -1:
                self.setCurrentBlockState(1)
                commentLength = len(text) - startIndex
            else:
                endMatch = self.valueEndExpression.match(text, endIndex)
                commentLength = endIndex - startIndex + endMatch.capturedLength()

            self.setFormat(startIndex, commentLength, self.valueFormat)
            startIndex = self._match_start(
                self.valueStartExpression,
                text,
                startIndex + max(commentLength, 1),
            )

        for word in self.searchRules:
            if not word:
                continue
            expression = QRegularExpression(
                word,
                QRegularExpression.PatternOption.CaseInsensitiveOption,
            )
            self._apply_regex_format(
                expression,
                text,
                self._searchFormat(),
                self.setFormat,
            )

    @staticmethod
    def _searchFormat():
        keywordFormat = QTextCharFormat()
        keywordFormat.setBackground(QColor("#FF0000"))
        return keywordFormat


class SearchHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.searchRules = []

    def highlightBlock(self, text):
        for word in self.searchRules:
            if not word:
                continue
            expression = QRegularExpression(
                word,
                QRegularExpression.PatternOption.CaseInsensitiveOption,
            )
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                keywordFormat = QTextCharFormat()
                keywordFormat.setBackground(QColor("#FF0000"))
                self.setFormat(match.capturedStart(), match.capturedLength(), keywordFormat)


class QCodeEditor(QPlainTextEdit):
    '''
    QCodeEditor inherited from QPlainTextEdit providing:
        numberBar - set by DISPLAY_LINE_NUMBERS flag equals True
        curent line highligthing - set by HIGHLIGHT_CURRENT_LINE flag equals True
        setting up QSyntaxHighlighter

    references:
        https://john.nachtimwald.com/2009/08/19/better-qplaintextedit-with-line-numbers/
        http://doc.qt.io/qt-5/qtwidgets-widgets-codeeditor-example.html
    '''

    class NumberBar(QWidget):
        '''class that deifnes textEditor numberBar'''

        def __init__(self, editor):
            QWidget.__init__(self, editor)

            self.editor = editor
            self.editor.blockCountChanged.connect(self.updateWidth)
            self.editor.updateRequest.connect(self.updateContents)
            self.font = QFont()
            self.numberBarColor = QColor("#171717")
            self.numberBarFontColor = QColor("#717171")
            self.numberBarSelectedFontColor = QColor("#FFFFFF")

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(event.rect(), self.numberBarColor)

            block = self.editor.firstVisibleBlock()

            while block.isValid():
                blockNumber = block.blockNumber()
                block_top = self.editor.blockBoundingGeometry(block).translated(
                    self.editor.contentOffset()
                ).top()

                if not block.isVisible() or block_top >= event.rect().bottom():
                    break

                if blockNumber == self.editor.textCursor().blockNumber() and self.editor.hasFocus():
                    self.font.setBold(True)
                    painter.setPen(self.numberBarSelectedFontColor)
                else:
                    self.font.setBold(False)
                    painter.setPen(self.numberBarFontColor)
                painter.setFont(self.font)

                paint_rect = QRect(0, int(block_top), self.width(), self.editor.fontMetrics().height())
                painter.drawText(
                    paint_rect,
                    Qt.AlignmentFlag.AlignRight,
                    str(blockNumber + 1),
                )

                block = block.next()

            painter.end()

            QWidget.paintEvent(self, event)

        def getWidth(self):
            count = self.editor.blockCount()
            width = self.fontMetrics().horizontalAdvance(str(count)) + 10
            return width

        def updateWidth(self):
            width = self.getWidth()
            if self.width() != width:
                self.setFixedWidth(width)
                self.editor.setViewportMargins(width, 0, 0, 0)

        def updateContents(self, rect, scroll):
            if scroll:
                self.scroll(0, scroll)
            else:
                self.update(0, rect.y(), self.width(), rect.height())

            if rect.contains(self.editor.viewport().rect()):
                fontSize = self.editor.currentCharFormat().font().pointSize()
                self.font.setPointSize(fontSize)
                self.font.setStyle(QFont.Style.StyleNormal)
                self.updateWidth()

    def __init__(self, DISPLAY_LINE_NUMBERS=True, HIGHLIGHT_CURRENT_LINE=True, SyntaxHighlighter=None, *args):
        super().__init__()

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.DISPLAY_LINE_NUMBERS = DISPLAY_LINE_NUMBERS

        if DISPLAY_LINE_NUMBERS:
            self.number_bar = self.NumberBar(self)

        if HIGHLIGHT_CURRENT_LINE:
            self.currentLineNumber = None
            self.currentLineColor = QColor("#171717")
            self.cursorPositionChanged.connect(self.highligtCurrentLine)
            self.original_out = self.focusOutEvent
            self.focusOutEvent = self.focusOut

        if SyntaxHighlighter is not None:
            self.highlighter = SyntaxHighlighter(self.document())

        self.appendPlainText("\n\n\n\n\n\n\n\n\n\n")
        self.clear()

    def changeStyle(self, isDarkMode):
        if isDarkMode:
            self.number_bar.numberBarColor = QColor("#171717")
            self.number_bar.numberBarFontColor = QColor("#717171")
            self.number_bar.numberBarSelectedFontColor = QColor("#FFFFFF")
            self.currentLineColor = QColor("#171717")
        else:
            self.number_bar.numberBarColor = QColor("#C1C1C1")
            self.number_bar.numberBarFontColor = QColor("#171717")
            self.number_bar.numberBarSelectedFontColor = QColor("#000000")
            self.currentLineColor = QColor("#C1C1C1")
        self.highligtCurrentLine(True)

    def focusOut(self, event):
        self.original_out(event)
        self.highligtCurrentLine(True)

    def resizeEvent(self, *e):
        if self.DISPLAY_LINE_NUMBERS:
            cr = self.contentsRect()
            rec = QRect(cr.left(), cr.top(), self.number_bar.getWidth(), cr.height())
            self.number_bar.setGeometry(rec)
        QPlainTextEdit.resizeEvent(self, *e)

    def highligtCurrentLine(self, hidden=False):
        if hidden:
            hi_selection = QTextEdit.ExtraSelection()
            hi_selection.cursor = self.textCursor()
            hi_selection.cursor.clearSelection()
            self.setExtraSelections([hi_selection])
        else:
            newCurrentLineNumber = self.textCursor().blockNumber()
            if newCurrentLineNumber != self.currentLineNumber:
                self.currentLineNumber = newCurrentLineNumber
                hi_selection = QTextEdit.ExtraSelection()
                hi_selection.format.setBackground(self.currentLineColor)
                hi_selection.format.setProperty(
                    QTextFormat.Property.FullWidthSelection,
                    True,
                )
                hi_selection.cursor = self.textCursor()
                hi_selection.cursor.clearSelection()
                self.setExtraSelections([hi_selection])
