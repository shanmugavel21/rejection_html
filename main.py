from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode="require"
    )


# --------------------------------------------------
# FAULT LIST
# --------------------------------------------------

FAULTS = [
    ("Conveyor", "Frame Coating Fault - MS"),
    ("Conveyor", "Leg / patti spot broken"),
    ("Conveyor", "Frame Dent"),
    ("Conveyor", "Rubber Leg Fault"),
    ("Conveyor", "Dial Plate Sticker Damage"),
    ("Conveyor", "Dial Plate Scratches / printing issues"),
    ("Conveyor", "Knob Scratches / printing issues"),
    ("Conveyor", "Glass Broken"),
    ("Conveyor", "Glass Acid mark / Printing issue"),
    ("Conveyor", "O Ring Fault"),
    ("Conveyor", "Fixed Tray - Small"),
    ("Conveyor", "Fixed Tray - Big"),
    ("Conveyor", "Fixed Tray - Jumbo"),
    ("Conveyor", "Bundy Tube Damage"),
    ("Conveyor", "Bundy Tube Leak"),
    ("Conveyor", "Mixing Tube Fault - Small"),
    ("Conveyor", "Mixing Tube Fault - Big"),
    ("Conveyor", "Mixing Tube Fault - Jumbo"),

    ("Process", "Mixing Tube Broken"),
    ("Process", "Sim OFF"),
    ("Process", "Sim HIGH"),
    ("Process", "Function Tight"),
    ("Process", "Flame LOW"),
    ("Process", "Flame HIGH"),
    ("Process", "Jet Block"),
    ("Process", "Pipe Block"),
    ("Process", "Burner Fault (W/O Pin)"),
    ("Process", "Burner Fault (I/O Flame)"),
    ("Process", "Burner Coating Fault"),
    ("Process", "Panstand Rejection - Seating / Bend"),
    ("Process", "Panstand Rejection - Coating fault"),
    ("Process", "Panstand Rejection - Pin removed"),
    ("Process", "PC Box Damage"),
    ("Process", "PC Box Vendor Rejection"),
    ("Process", "Dry Air Leak Testing")
]

FAULT_TO_SECTION = {
    fault: section
    for section, fault in FAULTS
}


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home():

    html_file = Path("templates/index.html")

    return html_file.read_text(
        encoding="utf-8"
    )


# --------------------------------------------------
# GET SHIFT DATA
# --------------------------------------------------

@app.get("/rejections")
def get_rejections(
    report_date: str,
    shift: str
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    fault_name,
                    supplier_rejection,
                    process_rejection
                FROM rejection_register
                WHERE report_date = %s
                AND shift = %s
            """, (
                report_date,
                shift
            ))

            rows = cur.fetchall()

    saved_data = {
        row[0]: {
            "supplier": row[1],
            "process": row[2]
        }
        for row in rows
    }

    data = []

    for section, fault in FAULTS:

        saved = saved_data.get(
            fault,
            {
                "supplier": 0,
                "process": 0
            }
        )

        data.append({
            "section": section,
            "fault_name": fault,
            "supplier": saved["supplier"],
            "process": saved["process"]
        })

    return {
        "date": report_date,
        "shift": shift,
        "data": data
    }


# --------------------------------------------------
# SAVE DATA MODELS
# --------------------------------------------------

class RejectionItem(BaseModel):

    fault_name: str
    supplier: int = 0
    process: int = 0


class RejectionData(BaseModel):

    report_date: str
    shift: str
    data: list[RejectionItem]


# --------------------------------------------------
# SAVE DATA
# --------------------------------------------------

@app.post("/save")
def save_rejections(payload: RejectionData):

    with get_connection() as conn:

        with conn.cursor() as cur:

            try:

                # Delete existing records for same date + shift
                cur.execute("""
                    DELETE FROM rejection_register
                    WHERE report_date = %s
                    AND shift = %s
                """, (
                    payload.report_date,
                    payload.shift
                ))

                for item in payload.data:

                    supplier = int(item.supplier or 0)
                    process = int(item.process or 0)

                    # Skip zero values
                    if supplier == 0 and process == 0:
                        continue

                    section = FAULT_TO_SECTION.get(
                        item.fault_name
                    )

                    cur.execute("""
                        INSERT INTO rejection_register
                        (
                            report_date,
                            shift,
                            section,
                            fault_name,
                            supplier_rejection,
                            process_rejection
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)

                        ON CONFLICT
                        (
                            report_date,
                            shift,
                            section,
                            fault_name
                        )

                        DO UPDATE SET
                            supplier_rejection = EXCLUDED.supplier_rejection,
                            process_rejection = EXCLUDED.process_rejection
                    """, (
                        payload.report_date,
                        payload.shift,
                        section,
                        item.fault_name,
                        supplier,
                        process
                    ))

                conn.commit()

                return {
                    "success": True,
                    "message": (
                        f"Saved successfully — "
                        f"{payload.report_date} | "
                        f"{payload.shift}"
                    )
                }

            except Exception as e:

                conn.rollback()

                return {
                    "success": False,
                    "message": str(e)
                }
# --------------------------------------------------
# DAILY TOTAL
# --------------------------------------------------

@app.get("/daily-total")
def daily_total(
    report_date: str
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    fault_name,
                    COALESCE(
                        SUM(supplier_rejection),
                        0
                    )
                    +
                    COALESCE(
                        SUM(process_rejection),
                        0
                    ) AS daily_total
                FROM rejection_register
                WHERE report_date = %s
                GROUP BY fault_name
            """, (
                report_date,
            ))

            rows = cur.fetchall()

    saved_data = {
        row[0]: int(row[1])
        for row in rows
    }

    data = []

    for section, fault in FAULTS:

        data.append({
            "fault_name": fault,
            "daily_total": saved_data.get(
                fault,
                0
            )
        })

    total = sum(
        item["daily_total"]
        for item in data
    )

    return {
        "date": report_date,
        "data": data,
        "total": total
    }


# --------------------------------------------------
# DELETE SHIFT DATA
# --------------------------------------------------

@app.delete("/delete")
def delete_data(
    report_date: str,
    shift: str
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            try:

                cur.execute("""
                    DELETE FROM rejection_register
                    WHERE report_date = %s
                    AND shift = %s
                """, (
                    report_date,
                    shift
                ))

                deleted_rows = cur.rowcount

                conn.commit()

                return {
                    "success": True,
                    "deleted_rows": deleted_rows,
                    "message": (
                        f"{deleted_rows} records "
                        f"deleted successfully."
                    )
                }

            except Exception as e:

                conn.rollback()

                return {
                    "success": False,
                    "message": str(e)
                }