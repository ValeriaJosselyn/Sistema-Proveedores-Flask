from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import psycopg2
from psycopg2.extras import RealDictCursor
import os

app = Flask(__name__)

# Clave para manejar sesiones
app.secret_key = "sistema_proveedores_2026"
# ==========================
# CONEXIÓN A SUPABASE
# ==========================

def conectar_bd():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
        port=os.getenv("DB_PORT")
    )


# ==========================
# PÁGINA PRINCIPAL
# ==========================

@app.route("/", methods=["GET", "POST"])
def inicio():

    error = None

    if request.method == "POST":

        nombre = request.form.get("usuario", "").lower().strip()

        try:
            conexion = conectar_bd()
            cursor = conexion.cursor(cursor_factory=RealDictCursor)

            cursor.execute(
                """
                SELECT *
                FROM usuario
                WHERE LOWER(nombre_usuario) = LOWER(%s)
                """,
                (nombre,)
            )

            usuario = cursor.fetchone()

            cursor.close()
            conexion.close()

            if usuario:

                session["id_usuario"] = usuario["id"]
                session["usuario"] = usuario["nombre_usuario"]

                return redirect(url_for("buscar"))

            else:

                error = "Administrador no encontrado."

        except psycopg2.Error as e:

            print("Error al consultar usuario:", e)
            error = "No se pudo conectar con la base de datos."

    return render_template(
        "index.html",
        error=error
    )


# ==========================
# BUSCADOR
# ==========================

@app.route("/buscar")
def buscar():

    admin_id = session.get("id_usuario")

    if not admin_id:
        return redirect(url_for("inicio"))

    return render_template(
        "buscar.html",
        admin_id=admin_id
    )


# ==========================
# API DEL BUSCADOR
# ==========================

@app.route("/buscar_api", methods=["GET"])
def buscar_api():

    proveedores = []

    busqueda = request.args.get("buscar", "").strip()
    admin_id = request.args.get("admin_id")

    if not admin_id:
        return jsonify([])

    try:

        conexion = conectar_bd()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        if busqueda:

            consulta = """
                SELECT *
                FROM proveedor
                WHERE (
                    nombre_proveedor ILIKE %s
                    OR nombre_empresa ILIKE %s
                    OR descripcion ILIKE %s
                    OR telefono ILIKE %s
                    OR correo ILIKE %s
                )
                AND id_usuario = %s
            """

            dato = f"%{busqueda}%"

            cursor.execute(
                consulta,
                (
                    dato,
                    dato,
                    dato,
                    dato,
                    dato,
                    admin_id
                )
            )

            proveedores = cursor.fetchall()

        cursor.close()
        conexion.close()

    except psycopg2.Error as e:

        print("Error en buscar_api:", e)

        return jsonify([])

    return jsonify(proveedores)


# ==========================
# LOGIN
# ==========================

@app.route("/login")
def login():

    return render_template("login.html")


# ==========================
# VALIDAR LOGIN
# ==========================

@app.route("/validar_login", methods=["POST"])
def validar_login():

    usuario = request.form.get("usuario", "").strip()
    contrasena = request.form.get("contrasena", "")

    try:

        conexion = conectar_bd()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        sql = """
            SELECT *
            FROM usuario
            WHERE LOWER(nombre_usuario) = LOWER(%s)
            AND contrasena = %s
        """

        cursor.execute(
            sql,
            (
                usuario,
                contrasena
            )
        )

        datos = cursor.fetchone()

        cursor.close()
        conexion.close()

        if datos:

            session["id_usuario"] = datos["id"]
            session["usuario"] = datos["nombre_usuario"]

            return redirect(url_for("panel"))

        else:

            return "Usuario o contraseña incorrectos"

    except psycopg2.Error as e:

        print("Error en login:", e)

        return "Error al conectar con la base de datos."


# ==========================
# PANEL
# ==========================

@app.route("/panel")
def panel():

    if "usuario" not in session:

        return redirect(url_for("login"))

    print(session)

    return render_template(
        "panel.html",
        usuario=session["usuario"]
    )


# ==========================
# MIS PROVEEDORES
# ==========================

@app.route("/proveedores")
def mis_proveedores():

    if "usuario" not in session:

        return redirect(url_for("login"))

    id_admin = session["id_usuario"]

    try:

        conexion = conectar_bd()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        # Mostramos únicamente los proveedores
        # pertenecientes al administrador actual

        cursor.execute(
            """
            SELECT *
            FROM proveedor
            WHERE id_usuario = %s
            """,
            (id_admin,)
        )

        mis_provs = cursor.fetchall()

        cursor.close()
        conexion.close()

        return render_template(
            "proveedores.html",
            proveedores=mis_provs,
            usuario=session["usuario"]
        )

    except psycopg2.Error as e:

        print("Error al consultar proveedores:", e)

        return "Error al consultar los proveedores."


# ==========================
# AGREGAR PROVEEDOR
# ==========================

@app.route("/agregar", methods=["GET", "POST"])
def agregar_provider():

    if "usuario" not in session:

        return redirect(url_for("login"))

    if request.method == "POST":

        nombre = request.form.get("nombre")
        empresa = request.form.get("empresa")
        telefono = request.form.get("telefono")
        correo = request.form.get("correo")
        descripcion = request.form.get("descripcion")

        id_admin = session["id_usuario"]

        try:

            conexion = conectar_bd()
            cursor = conexion.cursor()

            consulta = """
                INSERT INTO proveedor
                (
                    nombre_proveedor,
                    nombre_empresa,
                    telefono,
                    correo,
                    descripcion,
                    id_usuario
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """

            cursor.execute(
                consulta,
                (
                    nombre,
                    empresa,
                    telefono,
                    correo,
                    descripcion,
                    id_admin
                )
            )

            conexion.commit()

            cursor.close()
            conexion.close()

            return redirect(url_for("mis_proveedores"))

        except psycopg2.Error as e:

            print("Error al agregar proveedor:", e)

            return "Error al agregar el proveedor."

    return render_template("agregar.html")


# ==========================
# EDITAR PROVEEDOR
# ==========================

@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar_proveedor(id):

    if "usuario" not in session:

        return redirect(url_for("login"))

    try:

        conexion = conectar_bd()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        if request.method == "POST":

            nombre = request.form.get("nombre")
            empresa = request.form.get("empresa")
            telefono = request.form.get("telefono")
            correo = request.form.get("correo")
            descripcion = request.form.get("descripcion")

            consulta = """
                UPDATE proveedor
                SET
                    nombre_proveedor = %s,
                    nombre_empresa = %s,
                    telefono = %s,
                    correo = %s,
                    descripcion = %s
                WHERE id = %s
                AND id_usuario = %s
            """

            cursor.execute(
                consulta,
                (
                    nombre,
                    empresa,
                    telefono,
                    correo,
                    descripcion,
                    id,
                    session["id_usuario"]
                )
            )

            conexion.commit()

            cursor.close()
            conexion.close()

            return redirect(url_for("mis_proveedores"))

        # Buscar proveedor actual

        cursor.execute(
            """
            SELECT *
            FROM proveedor
            WHERE id = %s
            AND id_usuario = %s
            """,
            (
                id,
                session["id_usuario"]
            )
        )

        proveedor = cursor.fetchone()

        cursor.close()
        conexion.close()

        if not proveedor:

            return "Proveedor no encontrado o no tienes permisos.", 404

        return render_template(
            "editar.html",
            p=proveedor
        )

    except psycopg2.Error as e:

        print("Error al editar proveedor:", e)

        return "Error al editar el proveedor."


# ==========================
# ELIMINAR PROVEEDOR
# ==========================

@app.route("/eliminar/<int:id>")
def eliminar_proveedor(id):

    if "usuario" not in session:

        return redirect(url_for("login"))

    try:

        conexion = conectar_bd()
        cursor = conexion.cursor()

        # Eliminamos únicamente si el proveedor
        # pertenece al administrador actual

        cursor.execute(
            """
            DELETE FROM proveedor
            WHERE id = %s
            AND id_usuario = %s
            """,
            (
                id,
                session["id_usuario"]
            )
        )

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(url_for("mis_proveedores"))

    except psycopg2.Error as e:

        print("Error al eliminar proveedor:", e)

        return "Error al eliminar el proveedor."


# ==========================
# CAMBIAR CONTRASEÑA
# ==========================

@app.route("/restablecer_contrasena", methods=["GET", "POST"])
def restablecer_contrasena():

    error = None
    exito = None

    if request.method == "POST":

        usuario = request.form.get("usuario", "").strip()
        nueva = request.form.get("nueva", "").strip()
        confirmar = request.form.get("confirmar", "").strip()

        if nueva != confirmar:

            error = "Las contraseñas no coinciden."

        else:

            try:

                conexion = conectar_bd()
                cursor = conexion.cursor(cursor_factory=RealDictCursor)

                cursor.execute(
                    """
                    SELECT id
                    FROM usuario
                    WHERE LOWER(nombre_usuario) = LOWER(%s)
                    """,
                    (usuario,)
                )

                datos = cursor.fetchone()

                if datos:

                    id_admin = datos["id"]

                    cursor.execute(
                        """
                        UPDATE usuario
                        SET contrasena = %s
                        WHERE id = %s
                        """,
                        (
                            nueva,
                            id_admin
                        )
                    )

                    conexion.commit()

                    exito = "Contraseña actualizada correctamente."

                else:

                    error = "Usuario no encontrado."

                cursor.close()
                conexion.close()

            except psycopg2.Error as e:

                print("Error al cambiar contraseña:", e)

                error = "No se pudo actualizar la contraseña."

    return render_template(
        "restablecer_contrasena.html",
        error=error,
        exito=exito
    )


# ==========================
# CERRAR SESIÓN
# ==========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("inicio"))


# ==========================
# FAVICON
# ==========================

@app.route("/favicon.ico")
def favicon():

    return "", 204


# ==========================
# EJECUTAR APLICACIÓN
# ==========================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )

