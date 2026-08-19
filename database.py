import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================
# DATABASE CONNECTION
# ============================================

def get_connection():

    if not DATABASE_URL:
        raise Exception(
            "DATABASE_URL is not configured"
        )

    return psycopg2.connect(
        DATABASE_URL
    )


# ============================================
# GET DUE REPORTS
# ============================================

def get_due_reports():

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        """
        Pick all reports that are due.

        SKIP LOCKED prevents two runner processes
        from picking the same report.
        """

        cursor.execute("""
            SELECT
                r.id,
                r.client_id,
                c.name AS client_name,
                r.report_name,
                r.data_source,
                r.database_name,
                r.query,
                r.cron_expression,
                r.format,
                r.recipients,
                r.active,
                r.next_run_at,
                r.last_run_at,
                r.status,
                r.last_started_at,
                r.retry_count,
                r.max_retries,
                r.last_error,
                r.brands
            FROM reports r
            JOIN clients c
                ON r.client_id = c.id
            WHERE r.active = TRUE
              AND r.next_run_at <= NOW()
              AND r.status != 'RUNNING'
              AND (
                    r.status != 'FAILED'
                    OR r.retry_count < r.max_retries
                  )
            ORDER BY r.next_run_at
            FOR UPDATE OF r SKIP LOCKED;
        """)

        reports = cursor.fetchall()

        # Convert rows to dictionaries
        columns = [
            desc[0]
            for desc in cursor.description
        ]

        reports = [
            dict(zip(columns, row))
            for row in reports
        ]

        connection.commit()

        return reports

    except Exception as error:

        if connection:
            connection.rollback()

        print(
            "Error getting due reports:",
            error
        )

        return []

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================
# MARK REPORT AS RUNNING
# ============================================

def mark_report_running(report_id):

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE reports
            SET
                status = 'RUNNING',
                last_started_at = NOW(),
                updated_at = NOW()
            WHERE id = %s;
        """, (
            report_id,
        ))

        connection.commit()

        print(
            f"Report {report_id} marked RUNNING"
        )

    except Exception as error:

        if connection:
            connection.rollback()

        raise error

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================
# MARK REPORT AS SUCCESS
# ============================================

def mark_report_success(
    report_id,
    next_run_at
):

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE reports
            SET
                status = 'PENDING',
                last_run_at = NOW(),
                next_run_at = %s,
                retry_count = 0,
                last_error = NULL,
                updated_at = NOW()
            WHERE id = %s;
        """, (
            next_run_at,
            report_id
        ))

        connection.commit()

        print(
            f"Report {report_id} completed successfully. "
            f"Next run: {next_run_at}"
        )

    except Exception as error:

        if connection:
            connection.rollback()

        raise error

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================
# MARK REPORT AS FAILURE
# ============================================

def mark_report_failure(
    report_id,
    retry_count,
    max_retries,
    error_message
):

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        new_retry_count = retry_count + 1

        if new_retry_count >= max_retries:

            status = "FAILED"

        else:

            status = "PENDING"

        cursor.execute("""
            UPDATE reports
            SET
                status = %s,
                retry_count = %s,
                last_error = %s,
                updated_at = NOW()
            WHERE id = %s;
        """, (
            status,
            new_retry_count,
            str(error_message),
            report_id
        ))

        connection.commit()

        print(
            f"Report {report_id} failed. "
            f"Retry: {new_retry_count}/{max_retries} "
            f"Status: {status}"
        )

    except Exception as error:

        if connection:
            connection.rollback()

        raise error

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()