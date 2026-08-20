import os
import io
import re
import requests

from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Image
)


def generate_pdf(dataframe, report_name):

    # ============================================================
    # CONFIG
    # ============================================================

    OUTPUT_DIR = "generated_reports"

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    filename = os.path.join(
        OUTPUT_DIR,
        f"{report_name}.pdf"
    )

    # Actual thumbnail resolution (pixels).
    # The cell only *displays* the image at ~25pt (~0.35 inch), but
    # PDFs are still viewed zoomed-in and often printed, so the source
    # bitmap needs far more pixels than the display box to look sharp.
    # 30px was the old value and produced ~85 DPI at display size,
    # which reads as blurry/blocky. 150px gives ~430 DPI at the same
    # display size (crisp even zoomed in or printed), while still
    # keeping each thumbnail's file size small (a few KB).
    THUMBNAIL_SIZE = 150

    # JPEG quality. 60 introduces visible compression artifacts at
    # this size; 85 is close to visually lossless with only a modest
    # file-size increase.
    THUMBNAIL_QUALITY = 85

    # Download timeout.
    IMAGE_TIMEOUT = 10

    # Max box a thumbnail is allowed to occupy in the table cell.
    # The actual rendered size is scaled to fit inside this box while
    # preserving the image's original aspect ratio (fixes distorted /
    # inconsistently sized thumbnails).
    IMAGE_BOX_WIDTH = 25
    IMAGE_BOX_HEIGHT = 25

    # ============================================================
    # PAGE
    # ============================================================

    PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)

    document = SimpleDocTemplate(
        filename,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=20,
        bottomMargin=20
    )

    available_width = (
        PAGE_WIDTH
        - document.leftMargin
        - document.rightMargin
    )

    # ============================================================
    # STYLES
    # ============================================================

    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        alignment=TA_CENTER,
        textColor=colors.white
    )

    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=6.5,
        leading=7.5,
        alignment=TA_LEFT
    )

    # ============================================================
    # TEXT SANITIZATION
    # ============================================================

    # The base-14 PDF fonts (Helvetica, etc.) do not contain a glyph
    # for the Rupee sign (U+20B9 "₹"). ReportLab silently renders any
    # unsupported glyph as a solid black box ("tofu"), which is the
    # black square seen before every price in the report. Rather than
    # depending on a bundled Unicode TTF being available at render
    # time, we normalize the character to plain ASCII "Rs. " so it
    # renders correctly with any font.
    UNSUPPORTED_GLYPH_MAP = {
        "\u20b9": "Rs. ",   # ₹ INR
        "\u2022": "- ",     # • bullet, just in case
    }

    def sanitize_text(text):

        for bad_char, replacement in UNSUPPORTED_GLYPH_MAP.items():
            text = text.replace(bad_char, replacement)

        # Catch-all: strip any other character outside the safe
        # Latin-1 range that Helvetica can't render, so it degrades
        # to nothing instead of a black box.
        text = re.sub(r"[^\x00-\xFF]", "", text)

        return text

    # ============================================================
    # GENERIC NUMERIC / CURRENCY VALUE DETECTION
    # ============================================================
    # Instead of hard-coding a specific column name (e.g. a
    # "_price_range" suffix), we detect columns that are right-align
    # candidates by looking at the *values* themselves. This makes
    # the report work for any dataframe, regardless of what its
    # columns happen to be called.

    NUMERIC_VALUE_PATTERN = re.compile(
        r"^[\s]*[₹$€£]?[\s]*"        # optional leading currency symbol
        r"\d[\d,]*(\.\d+)?"          # a number
        r"([\s]*-[\s]*"              # optional range separator
        r"[₹$€£]?[\s]*\d[\d,]*(\.\d+)?)?"  # optional second number
        r"[\s]*[%]?[\s]*$"           # optional trailing percent sign
    )

    def looks_numeric_or_currency(value):

        if value is None:
            return False

        text = str(value).strip()

        if not text or text.lower() in ("nan", "none", "null"):
            return False

        return bool(NUMERIC_VALUE_PATTERN.match(text))

    def is_numeric_column(dataframe, column):

        try:
            values = dataframe[column].dropna().head(50)
        except Exception:
            return False

        checked = 0
        matched = 0

        for value in values:

            text = str(value).strip()

            if not text or text.lower() in ("nan", "none", "null"):
                continue

            checked += 1

            if looks_numeric_or_currency(text):
                matched += 1

        if checked == 0:
            return False

        # Treat as a numeric/currency column if the large majority
        # of its non-empty sampled values look numeric.
        return (matched / checked) >= 0.8

    # ============================================================
    # IMAGE CACHE
    # ============================================================

    image_cache = {}

    def get_thumbnail(value):

        """
        Automatically detects image URLs by examining the actual
        cell value.

        A value is treated as an image only when:

        1. It starts with http:// or https://
        2. The downloaded content can actually be opened by Pillow.

        Non-image URLs remain normal text.
        """

        if value is None:
            return None

        value = str(value).strip()

        if not value:
            return None

        if value.lower() in (
            "nan",
            "none",
            "null"
        ):
            return None

        # --------------------------------------------------------
        # Must be HTTP/HTTPS
        # --------------------------------------------------------

        if not value.lower().startswith(
            (
                "http://",
                "https://"
            )
        ):
            return None

        # --------------------------------------------------------
        # CACHE
        # --------------------------------------------------------

        if value in image_cache:
            return image_cache[value]

        try:

            # ----------------------------------------------------
            # DOWNLOAD
            # ----------------------------------------------------

            response = requests.get(
                value,
                timeout=IMAGE_TIMEOUT,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            response.raise_for_status()

            # ----------------------------------------------------
            # OPEN WITH PILLOW
            # ----------------------------------------------------

            source_buffer = io.BytesIO(
                response.content
            )

            pil_image = PILImage.open(
                source_buffer
            )

            # Fully load image.
            pil_image.load()

            # ----------------------------------------------------
            # CENTER-CROP TO SQUARE, THEN RESIZE
            # ----------------------------------------------------
            # Scaling to "fit inside" a box while preserving aspect
            # ratio (the previous approach) leaves wide/tall images
            # much smaller than square ones, with empty space around
            # them ("shrunk" thumbnails). Product photos are commonly
            # displayed as uniform squares, so instead we center-crop
            # each image to a square first (no stretching/distortion,
            # just trims the longer side) and then resize that square
            # to a fixed target size. Every thumbnail now fills its
            # cell consistently regardless of the source aspect ratio.

            native_width, native_height = pil_image.size

            crop_side = min(native_width, native_height)

            left = (native_width - crop_side) // 2
            top = (native_height - crop_side) // 2

            pil_image = pil_image.crop(
                (
                    left,
                    top,
                    left + crop_side,
                    top + crop_side
                )
            )

            pil_image = pil_image.resize(
                (
                    THUMBNAIL_SIZE,
                    THUMBNAIL_SIZE
                ),
                PILImage.Resampling.LANCZOS
            )

            # ----------------------------------------------------
            # CONVERT TO RGB
            # ----------------------------------------------------

            if pil_image.mode != "RGB":

                # Handle transparency correctly.
                if pil_image.mode in (
                    "RGBA",
                    "LA"
                ):

                    background = PILImage.new(
                        "RGB",
                        pil_image.size,
                        "white"
                    )

                    background.paste(
                        pil_image,
                        mask=pil_image.getchannel(
                            "A"
                        )
                    )

                    pil_image = background

                else:

                    pil_image = pil_image.convert(
                        "RGB"
                    )

            # ----------------------------------------------------
            # CREATE REAL SMALL JPEG
            # ----------------------------------------------------

            thumbnail_buffer = io.BytesIO()

            pil_image.save(
                thumbnail_buffer,
                format="JPEG",
                quality=THUMBNAIL_QUALITY,
                optimize=True
            )

            thumbnail_buffer.seek(0)

            # ----------------------------------------------------
            # CREATE REPORTLAB IMAGE
            # ----------------------------------------------------
            # pil_image is now guaranteed square, so rendering it at
            # a fixed IMAGE_BOX_WIDTH x IMAGE_BOX_HEIGHT introduces no
            # distortion, and every thumbnail is the same size.

            thumbnail = Image(
                thumbnail_buffer,
                width=IMAGE_BOX_WIDTH,
                height=IMAGE_BOX_HEIGHT
            )

            # ----------------------------------------------------
            # CACHE
            # ----------------------------------------------------

            image_cache[value] = thumbnail

            return thumbnail

        except Exception as error:

            print(
                f"Unable to process image URL: {value}"
            )

            print(
                f"Reason: {type(error).__name__}: {error}"
            )

            image_cache[value] = None

            return None

    # ============================================================
    # COLUMNS
    # ============================================================

    columns = list(
        dataframe.columns
    )

    if not columns:

        raise ValueError(
            "Cannot generate PDF: dataframe has no columns."
        )

    print(
        "Columns:",
        columns
    )

    # ============================================================
    # DETERMINE IMAGE CELLS
    # ============================================================

    image_cells = {}

    for row_index, (_, row) in enumerate(
        dataframe.iterrows(),
        start=1
    ):

        for column_index, column in enumerate(
            columns
        ):

            value = row[column]

            thumbnail = get_thumbnail(
                value
            )

            if thumbnail:

                image_cells[
                    (
                        row_index,
                        column_index
                    )
                ] = thumbnail

    print(
        "Image cells found:",
        len(image_cells)
    )

    # ============================================================
    # COLUMN WIDTHS
    # ============================================================

    IMAGE_COLUMN_WIDTH = 35
    MIN_COLUMN_WIDTH = 45
    MAX_COLUMN_WIDTH = 140

    column_widths = []

    # ------------------------------------------------------------
    # Determine image columns
    # ------------------------------------------------------------

    image_column_indexes = set()

    for (
        row_index,
        column_index
    ) in image_cells.keys():

        image_column_indexes.add(
            column_index
        )

    # ------------------------------------------------------------
    # Calculate width for every column
    # ------------------------------------------------------------

    for column_index, column in enumerate(
        columns
    ):

        # --------------------------------------------------------
        # IMAGE COLUMN
        # --------------------------------------------------------

        if column_index in image_column_indexes:

            column_widths.append(
                IMAGE_COLUMN_WIDTH
            )

            continue

        # --------------------------------------------------------
        # HEADER LENGTH
        # --------------------------------------------------------

        header_length = len(
            str(column)
        )

        # --------------------------------------------------------
        # DATA LENGTH
        # --------------------------------------------------------

        max_value_length = 0

        try:

            values = dataframe[column].dropna()

            for value in values.head(100):

                text = str(value)

                max_value_length = max(
                    max_value_length,
                    len(text)
                )

        except Exception:

            max_value_length = 0

        # --------------------------------------------------------
        # WIDTH
        # --------------------------------------------------------

        content_length = max(
            header_length,
            max_value_length
        )

        calculated_width = (
            content_length * 4.5
        )

        calculated_width = max(
            MIN_COLUMN_WIDTH,
            calculated_width
        )

        calculated_width = min(
            MAX_COLUMN_WIDTH,
            calculated_width
        )

        column_widths.append(
            calculated_width
        )

    # ============================================================
    # SCALE TO PAGE WIDTH
    # ============================================================

    total_width = sum(
        column_widths
    )

    if total_width > available_width:

        scale = (
            available_width
            / total_width
        )

        column_widths = [
            width * scale
            for width in column_widths
        ]

    # ============================================================
    # WIDTH INFORMATION
    # ============================================================

    print(
        "Available page width:",
        available_width
    )

    print(
        "Table width:",
        sum(column_widths)
    )

    # ============================================================
    # BUILD TABLE DATA
    # ============================================================

    table_data = []

    # ============================================================
    # HEADER
    # ============================================================

    header_row = []

    for column in columns:

        header_row.append(
            Paragraph(
                sanitize_text(str(column)),
                header_style
            )
        )

    table_data.append(
        header_row
    )

    # ============================================================
    # DATA ROWS
    # ============================================================

    for row_index, (_, row) in enumerate(
        dataframe.iterrows(),
        start=1
    ):

        table_row = []

        for column_index, column in enumerate(
            columns
        ):

            value = row[column]

            # ----------------------------------------------------
            # CHECK IMAGE
            # ----------------------------------------------------

            thumbnail = image_cells.get(
                (
                    row_index,
                    column_index
                )
            )

            if thumbnail:

                table_row.append(
                    thumbnail
                )

                continue

            # ----------------------------------------------------
            # HANDLE NULL / NAN
            # ----------------------------------------------------

            if value is None:

                value = ""

            elif str(value).lower() in (
                "nan",
                "none",
                "null"
            ):

                value = ""

            # ----------------------------------------------------
            # NORMAL TEXT
            # ----------------------------------------------------

            text = str(
                value
            )

            # ----------------------------------------------------
            # STRIP GLYPHS THE PDF FONT CAN'T RENDER (e.g. ₹)
            # ----------------------------------------------------

            text = sanitize_text(text)

            # ----------------------------------------------------
            # ESCAPE HTML
            # ----------------------------------------------------

            text = (
                text
                .replace(
                    "&",
                    "&amp;"
                )
                .replace(
                    "<",
                    "&lt;"
                )
                .replace(
                    ">",
                    "&gt;"
                )
            )

            table_row.append(
                Paragraph(
                    text,
                    cell_style
                )
            )

        table_data.append(
            table_row
        )

    # ============================================================
    # TABLE
    # ============================================================

    table = Table(
        table_data,
        colWidths=column_widths,
        repeatRows=1,
        splitByRow=1
    )

    # ============================================================
    # TABLE STYLE
    # ============================================================

    table_styles = [

        # --------------------------------------------------------
        # HEADER
        # --------------------------------------------------------

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.grey
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            colors.white
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold"
        ),

        # --------------------------------------------------------
        # HEADER ALIGNMENT
        # --------------------------------------------------------

        (
            "ALIGN",
            (0, 0),
            (-1, 0),
            "CENTER"
        ),

        # --------------------------------------------------------
        # VERTICAL ALIGNMENT
        # --------------------------------------------------------

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE"
        ),

        # --------------------------------------------------------
        # GRID
        # --------------------------------------------------------

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.4,
            colors.black
        ),

        # --------------------------------------------------------
        # PADDING
        # --------------------------------------------------------

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            3
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            3
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            2
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            2
        )
    ]

    # ============================================================
    # CENTER IMAGE CELLS (both horizontally and vertically)
    # ============================================================

    for (
        row_index,
        column_index
    ) in image_cells.keys():

        table_styles.append(
            (
                "ALIGN",
                (
                    column_index,
                    row_index
                ),
                (
                    column_index,
                    row_index
                ),
                "CENTER"
            )
        )

        table_styles.append(
            (
                "VALIGN",
                (
                    column_index,
                    row_index
                ),
                (
                    column_index,
                    row_index
                ),
                "MIDDLE"
            )
        )

    # ============================================================
    # RIGHT-ALIGN NUMERIC / CURRENCY COLUMNS
    # ============================================================
    # Detected generically from the column's actual values (see
    # is_numeric_column above), so this works for any dataframe
    # rather than only columns named "*_price_range".

    for column_index, column in enumerate(columns):

        if column_index in image_column_indexes:
            continue

        if is_numeric_column(dataframe, column):

            table_styles.append(
                (
                    "ALIGN",
                    (
                        column_index,
                        1
                    ),
                    (
                        column_index,
                        -1
                    ),
                    "RIGHT"
                )
            )

    # ============================================================
    # APPLY TABLE STYLE
    # ============================================================

    table.setStyle(
        TableStyle(
            table_styles
        )
    )

    # ============================================================
    # CENTER TABLE ON PAGE
    # ============================================================

    table.hAlign = "CENTER"

    # ============================================================
    # GENERATE PDF
    # ============================================================

    document.build(
        [table]
    )

    print(
        f"PDF generated: {filename}"
    )

    return filename
