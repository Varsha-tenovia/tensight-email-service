import os
import json
import traceback

from datetime import datetime, timezone

from database import (
    get_due_reports,
    mark_report_running,
    mark_report_success,
    mark_report_failure
)

from motherduck import execute_query as execute_motherduck
from athena import execute_query as execute_athena

from csv_generator import generate_csv
from pdf_generator import generate_pdf

from email_service import send_email

from scheduler import get_next_run


# ============================================
# GET BRANDS FROM REPORT
# ============================================

def get_report_brands(report):

    brands = report.get("brands")

    # ----------------------------------------
    # No brands configured
    # ----------------------------------------

    if not brands:
        return None

    # ----------------------------------------
    # JSON string from PostgreSQL
    # ----------------------------------------

    if isinstance(brands, str):

        try:

            brands = json.loads(brands)

        except json.JSONDecodeError:

            # In case PostgreSQL returns:
            # Jack&Jones,Vero Moda,ONLY,Selected Homme

            brands = [
                brand.strip()
                for brand in brands.split(",")
                if brand.strip()
            ]

    # ----------------------------------------
    # Make sure it is a list
    # ----------------------------------------

    if not isinstance(brands, list):

        raise Exception(
            "Invalid brands configuration. "
            "Expected a list."
        )

    return brands


# ============================================
# GENERATE SAFE FILENAME
# ============================================

def get_safe_filename(report_name, suffix=None):

    safe_report_name = (
        report_name
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    if suffix:

        safe_suffix = (
            suffix
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace("&", "and")
        )

        return (
            f"{safe_report_name}_"
            f"{safe_suffix}_"
            f"{timestamp}"
        )

    return (
        f"{safe_report_name}_"
        f"{timestamp}"
    )


# ============================================
# EXECUTE QUERY
# ============================================

def execute_report_query(
    data_source,
    query,
    database_name
):

    if data_source == "motherduck":

        return execute_motherduck(
            query=query,
            database_name=database_name
        )

    elif data_source == "athena":

        return execute_athena(
            query=query,
            database_name=database_name
        )

    else:

        raise Exception(
            f"Unsupported data source: "
            f"{data_source}"
        )


# ============================================
# PROCESS ONE REPORT
# ============================================

def process_report(report):

    report_id = report["id"]

    report_name = report["report_name"]

    client_name = report["client_name"]

    data_source = (
        report["data_source"]
        .lower()
        .strip()
    )

    database_name = report["database_name"]

    query = report["query"]

    report_format = (
        report["format"]
        .lower()
        .strip()
    )

    recipients = report["recipients"]

    cron_expression = (
        report["cron_expression"]
    )

    retry_count = report["retry_count"]

    max_retries = report["max_retries"]

    # ----------------------------------------
    # Get brands
    # ----------------------------------------

    brands = get_report_brands(report)

    print("\n===================================")

    print(
        f"Processing Report ID: {report_id}"
    )

    print(
        f"Client: {client_name}"
    )

    print(
        f"Report: {report_name}"
    )

    print(
        f"Data Source: {data_source}"
    )

    print(
        f"Format: {report_format}"
    )

    if brands:

        print(
            f"Brands: {brands}"
        )

    print(
        "===================================\n"
    )

    generated_files = []

    try:

        # ====================================
        # Mark RUNNING
        # ====================================

        mark_report_running(
            report_id
        )

        print(
            f"Report {report_id} marked RUNNING"
        )

        # ====================================
        # MULTI-BRAND REPORT
        # ====================================

        if brands:

            print(
                "Multi-brand report detected."
            )

            print(
                f"Total brands: {len(brands)}"
            )

            for brand in brands:

                print(
                    "\n-----------------------------------"
                )

                print(
                    f"Processing brand: {brand}"
                )

                print(
                    "-----------------------------------"
                )

                # --------------------------------
                # Replace {brand}
                # --------------------------------

                brand_query = query.replace(
                    "{brand}",
                    str(brand)
                )

                # --------------------------------
                # Execute query
                # --------------------------------

                dataframe = execute_report_query(
                    data_source=data_source,
                    query=brand_query,
                    database_name=database_name
                )

                print(
                    f"{brand} query completed. "
                    f"Rows returned: {len(dataframe)}"
                )

                # --------------------------------
                # Generate filename
                # --------------------------------

                filename = get_safe_filename(
                    report_name,
                    brand
                )

                # --------------------------------
                # Generate file
                # --------------------------------

                if report_format == "csv":

                    attachment_path = generate_csv(
                        dataframe,
                        filename
                    )

                elif report_format == "pdf":

                    attachment_path = generate_pdf(
                        dataframe,
                        filename
                    )

                else:

                    raise Exception(
                        f"Unsupported report format: "
                        f"{report_format}"
                    )

                generated_files.append(
                    attachment_path
                )

                print(
                    f"{brand} file generated: "
                    f"{attachment_path}"
                )

        # ====================================
        # NORMAL SINGLE REPORT
        # ====================================

        else:

            print(
                "Single report execution."
            )

            # --------------------------------
            # Execute query
            # --------------------------------

            dataframe = execute_report_query(
                data_source=data_source,
                query=query,
                database_name=database_name
            )

            print(
                f"Query completed. "
                f"Rows returned: {len(dataframe)}"
            )

            # --------------------------------
            # Generate filename
            # --------------------------------

            filename = get_safe_filename(
                report_name
            )

            # --------------------------------
            # Generate file
            # --------------------------------

            if report_format == "csv":

                attachment_path = generate_csv(
                    dataframe,
                    filename
                )

            elif report_format == "pdf":

                attachment_path = generate_pdf(
                    dataframe,
                    filename
                )

            else:

                raise Exception(
                    f"Unsupported report format: "
                    f"{report_format}"
                )

            generated_files.append(
                attachment_path
            )

            print(
                f"File generated: "
                f"{attachment_path}"
            )

        # ====================================
        # CHECK FILES
        # ====================================

        if not generated_files:

            raise Exception(
                "No report files were generated."
            )

        print(
            "\n-----------------------------------"
        )

        print(
            f"Generated files: "
            f"{len(generated_files)}"
        )

        for file_path in generated_files:

            print(
                f" - {file_path}"
            )

        print(
            "-----------------------------------"
        )

        # ====================================
        # SEND EMAIL
        # ====================================

        subject = (
            f"{client_name} - "
            f"{report_name}"
        )

        if brands:

            body = (
                f"Hi,\n\n"
                f"Please find attached the "
                f"{report_name} for "
                f"{client_name}.\n\n"
                f"Brands included:\n"
            )

            for brand in brands:

                body += (
                    f"- {brand}\n"
                )


        else:

             body = (
                f"Hi,\n\n"
                f"Please find attached the "
                f"{report_name} for "
                f"{client_name}."
            )

        send_email(
            recipients=recipients,
            subject=subject,
            body=body,
            attachment_paths=generated_files
        )

        print(
            f"Email sent successfully to: "
            f"{recipients}"
        )

        # ====================================
        # CALCULATE NEXT RUN
        # ====================================

        next_run_at = get_next_run(
            cron_expression
        )

        # ====================================
        # MARK SUCCESS
        # ====================================

        mark_report_success(
            report_id=report_id,
            next_run_at=next_run_at
        )

        print(
            f"Report {report_id} completed "
            f"successfully."
        )

        print(
            f"Next run: {next_run_at}"
        )

    except Exception as error:

        # ====================================
        # DETAILED ERROR LOGGING
        # ====================================

        print(
            f"\nReport {report_id} failed:"
        )

        print(
            f"Exception type: "
            f"{type(error).__name__}"
        )

        print(
            f"Exception repr: "
            f"{repr(error)}"
        )

        print(
            f"Exception string: "
            f"{str(error)}"
        )

        print(
            "\n========== FULL TRACEBACK =========="
        )

        traceback.print_exc()

        print(
            "====================================\n"
        )

        # ====================================
        # MARK FAILURE
        # ====================================

        try:

            mark_report_failure(
                report_id=report_id,
                retry_count=retry_count,
                max_retries=max_retries,
                error_message=(
                    f"{type(error).__name__}: "
                    f"{str(error)}"
                )
            )

        except Exception as failure_error:

            print(
                "\nFailed to update report "
                "failure status:"
            )

            print(
                f"Exception type: "
                f"{type(failure_error).__name__}"
            )

            print(
                f"Exception repr: "
                f"{repr(failure_error)}"
            )

            traceback.print_exc()

    finally:

        # ====================================
        # DELETE GENERATED FILES
        # ====================================

        for attachment_path in generated_files:

            try:

                if os.path.exists(
                    attachment_path
                ):

                    os.remove(
                        attachment_path
                    )

                    print(
                        f"Deleted generated file: "
                        f"{attachment_path}"
                    )

            except Exception as cleanup_error:

                print(
                    f"Could not delete file "
                    f"{attachment_path}: "
                    f"{cleanup_error}"
                )


# ============================================
# RUN REPORTS
# ============================================

def run_reports():

    print(
        "\n==================================="
    )

    print(
        "REPORT RUNNER STARTED"
    )

    print(
        datetime.now(
            timezone.utc
        )
    )

    print(
        "===================================\n"
    )

    reports = get_due_reports()

    print(
        f"Due reports found: {len(reports)}"
    )

    if not reports:

        print(
            "No reports to run."
        )

        return

    for report in reports:

        process_report(
            report
        )

    print(
        "\n==================================="
    )

    print(
        "REPORT RUNNER FINISHED"
    )

    print(
        "===================================\n"
    )