import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle
)


def generate_pdf(
    dataframe,
    report_name
):

    os.makedirs(
        "generated_reports",
        exist_ok=True
    )

    filename = (
        f"generated_reports/"
        f"{report_name}.pdf"
    )

    document = SimpleDocTemplate(
        filename,
        pagesize=landscape(A4)
    )

    data = [
        list(dataframe.columns)
    ]

    for row in dataframe.itertuples(
        index=False,
        name=None
    ):

        data.append(
            list(row)
        )

    table = Table(
        data,
        repeatRows=1
    )

    table.setStyle(
        TableStyle([
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
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.black
            ),
            (
                "ALIGN",
                (0, 0),
                (-1, -1),
                "CENTER"
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                7
            )
        ])
    )

    document.build([
        table
    ])

    print(
        f"PDF generated: {filename}"
    )

    return filename