import os


def generate_csv(
    dataframe,
    report_name
):

    os.makedirs(
        "generated_reports",
        exist_ok=True
    )

    filename = (
        f"generated_reports/"
        f"{report_name}.csv"
    )

    dataframe.to_csv(
        filename,
        index=False
    )

    print(
        f"CSV generated: {filename}"
    )

    return filename