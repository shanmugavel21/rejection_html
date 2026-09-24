from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode="require"
    )


# =========================================================
# FAULT LIST
# =========================================================

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


# =========================================================
# CREATE PRODUCTION TABLE
# =========================================================

def create_production_table():

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS production_register (
                    id SERIAL PRIMARY KEY,

                    report_date DATE NOT NULL,

                    shift VARCHAR(50) NOT NULL,

                    model_name VARCHAR(200) NOT NULL,

                    production_count INTEGER NOT NULL DEFAULT 0,

                    UNIQUE (
                        report_date,
                        shift,
                        model_name
                    )
                )
            """)

        conn.commit()


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
def startup():

    create_production_table()


# =========================================================
# HOME PAGE
# =========================================================

@app.get("/", response_class=HTMLResponse)
def home():

    html_file = (
        Path(__file__).resolve().parent
        / "templates"
        / "index.html"
    )

    return html_file.read_text(
        encoding="utf-8"
    )


# =========================================================
# GET REJECTION DATA
# =========================================================

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

                ORDER BY id
            """, (
                report_date,
                shift
            ))

            rows = cur.fetchall()


    saved_data = {

        row[0]: {
            "supplier": row[1] or 0,
            "process": row[2] or 0
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


    return data


# =========================================================
# GET PRODUCTION DATA
# =========================================================

@app.get("/production")
def get_production(
    report_date: str,
    shift: str
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    model_name,
                    production_count

                FROM production_register

                WHERE report_date = %s
                AND shift = %s

                ORDER BY id
            """, (
                report_date,
                shift
            ))

            rows = cur.fetchall()


    data = []


    for row in rows:

        data.append({

            "model_name": row[0],

            "production_count": row[1]

        })


    return data


# =========================================================
# SAVE DATA MODELS
# =========================================================

class RejectionItem(BaseModel):

    fault_name: str

    supplier: int = 0

    process: int = 0


class ProductionItem(BaseModel):

    model_name: str

    production_count: int = 0


class RejectionData(BaseModel):

    report_date: str

    shift: str

    data: list[RejectionItem] = []

    production: list[ProductionItem] = []


# =========================================================
# SAVE DATA
# =========================================================

@app.post("/save")
def save_data(
    payload: RejectionData
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            try:

                # -----------------------------------------
                # DELETE OLD REJECTION DATA
                # FOR THIS DATE + SHIFT
                # -----------------------------------------

                cur.execute("""
                    DELETE FROM rejection_register

                    WHERE report_date = %s
                    AND shift = %s
                """, (
                    payload.report_date,
                    payload.shift
                ))


                # -----------------------------------------
                # INSERT REJECTION DATA
                # -----------------------------------------

                for item in payload.data:

                    supplier = int(
                        item.supplier or 0
                    )

                    process = int(
                        item.process or 0
                    )


                    # Skip zero values

                    if supplier == 0 and process == 0:
                        continue


                    section = FAULT_TO_SECTION.get(
                        item.fault_name,
                        "Conveyor"
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

                        VALUES
                        (%s, %s, %s, %s, %s, %s)

                        ON CONFLICT
                        (
                            report_date,
                            shift,
                            section,
                            fault_name
                        )

                        DO UPDATE SET

                            supplier_rejection =
                                EXCLUDED.supplier_rejection,

                            process_rejection =
                                EXCLUDED.process_rejection
                    """, (
                        payload.report_date,
                        payload.shift,
                        section,
                        item.fault_name,
                        supplier,
                        process
                    ))


                # -----------------------------------------
                # DELETE OLD PRODUCTION DATA
                # FOR THIS DATE + SHIFT
                # -----------------------------------------

                cur.execute("""
                    DELETE FROM production_register

                    WHERE report_date = %s
                    AND shift = %s
                """, (
                    payload.report_date,
                    payload.shift
                ))


                # -----------------------------------------
                # INSERT PRODUCTION DATA
                # -----------------------------------------

                for item in payload.production:

                    model_name = (
                        item.model_name.strip()
                    )

                    count = int(
                        item.production_count or 0
                    )


                    if model_name == "":
                        continue


                    if count <= 0:
                        continue


                    cur.execute("""
                        INSERT INTO production_register
                        (
                            report_date,
                            shift,
                            model_name,
                            production_count
                        )

                        VALUES
                        (%s, %s, %s, %s)

                        ON CONFLICT
                        (
                            report_date,
                            shift,
                            model_name
                        )

                        DO UPDATE SET

                            production_count =
                                EXCLUDED.production_count
                    """, (
                        payload.report_date,
                        payload.shift,
                        model_name,
                        count
                    ))


                conn.commit()


                return {

                    "success": True,

                    "message":
                        f"Saved successfully — "
                        f"{payload.report_date} | "
                        f"{payload.shift}"

                }


            except Exception as e:

                conn.rollback()


                return {

                    "success": False,

                    "message": str(e)

                }


# =========================================================
# DAILY TOTAL
# =========================================================

@app.get("/daily-total")
def daily_total(
    report_date: str
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            # -----------------------------------------
            # SUPPLIER + PROCESS REJECTION
            # -----------------------------------------

            cur.execute("""
                SELECT

                    COALESCE(
                        SUM(supplier_rejection),
                        0
                    ),

                    COALESCE(
                        SUM(process_rejection),
                        0
                    )

                FROM rejection_register

                WHERE report_date = %s
            """, (
                report_date
            ))


            rejection_row = cur.fetchone()


            supplier_total = (
                rejection_row[0] or 0
            )


            process_total = (
                rejection_row[1] or 0
            )


            rejection_total = (
                supplier_total
                +
                process_total
            )


            # -----------------------------------------
            # TOTAL PRODUCTION
            # -----------------------------------------

            cur.execute("""
                SELECT

                    COALESCE(
                        SUM(production_count),
                        0
                    )

                FROM production_register

                WHERE report_date = %s
            """, (
                report_date
            ))


            production_total = (
                cur.fetchone()[0] or 0
            )


            # -----------------------------------------
            # SHIFT-WISE PRODUCTION
            # -----------------------------------------

            cur.execute("""
                SELECT

                    shift,

                    COALESCE(
                        SUM(production_count),
                        0
                    )

                FROM production_register

                WHERE report_date = %s

                GROUP BY shift

                ORDER BY

                    CASE

                        WHEN shift = '1st Shift'
                            THEN 1

                        WHEN shift = 'General Shift'
                            THEN 2

                        WHEN shift = '2nd Shift'
                            THEN 3

                        ELSE 4

                    END
            """, (
                report_date
            ))


            shift_rows = cur.fetchall()


            production_by_shift = []


            for row in shift_rows:

                production_by_shift.append({

                    "shift": row[0],

                    "count": row[1] or 0

                })


            # -----------------------------------------
            # MODEL-WISE PRODUCTION
            # -----------------------------------------

            cur.execute("""
                SELECT

                    model_name,

                    COALESCE(
                        SUM(production_count),
                        0
                    )

                FROM production_register

                WHERE report_date = %s

                GROUP BY model_name

                ORDER BY model_name
            """, (
                report_date
            ))


            model_rows = cur.fetchall()


            production_by_model = []


            for row in model_rows:

                production_by_model.append({

                    "model_name": row[0],

                    "count": row[1] or 0

                })


    return {

        "success": True,

        "report_date": report_date,

        "production_total":
            production_total,

        "supplier_total":
            supplier_total,

        "process_total":
            process_total,

        "rejection_total":
            rejection_total,

        "production_by_shift":
            production_by_shift,

        "production_by_model":
            production_by_model

    }


# =========================================================
# DELETE DATE + SHIFT
# =========================================================

@app.delete("/delete")
def delete_data(
    report_date: str,
    shift: str
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            try:

                # -----------------------------------------
                # DELETE REJECTION
                # -----------------------------------------

                cur.execute("""
                    DELETE FROM rejection_register

                    WHERE report_date = %s
                    AND shift = %s
                """, (
                    report_date,
                    shift
                ))


                rejection_deleted = cur.rowcount


                # -----------------------------------------
                # DELETE PRODUCTION
                # -----------------------------------------

                cur.execute("""
                    DELETE FROM production_register

                    WHERE report_date = %s
                    AND shift = %s
                """, (
                    report_date,
                    shift
                ))


                production_deleted = cur.rowcount


                conn.commit()


                return {

                    "success": True,

                    "rejection_deleted":
                        rejection_deleted,

                    "production_deleted":
                        production_deleted,

                    "message":
                        "Data deleted successfully"

                }


            except Exception as e:

                conn.rollback()


                return {

                    "success": False,

                    "message": str(e)

                }
