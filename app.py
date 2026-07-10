from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import mysql.connector
import config

app = Flask(__name__)

# Clave para manejar sesiones
app.secret_key = "sistema_proveedores_2026"

# ==========================
# CONEXIÓN
# ==========================
def conectar_bd():
    return mysql.connector.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        port=config.DB_PORT
    )
# ==========================
# PÁGINA PRINCIPAL
# ==========================
@app.route("/")
@app.route("/<nombre_admin>", methods=["GET"])
def inicio(nombre_admin="susana"):

    if nombre_admin.lower() not in ["susana", "ceci"]:
        return redirect(url_for("inicio"))

    session["ruta_publica"] = nombre_admin.lower()

    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT id FROM usuario WHERE nombre_usuario = %s",
        (nombre_admin.lower().strip(),)
    )

    usuario = cursor.fetchone()

    cursor.close()
    conexion.close()

    id_coincidencia = usuario["id"] if usuario else 1

    return render_template(
        "index.html",
        admin_id=id_coincidencia,
        nombre_admin=nombre_admin.capitalize()
    )

# ==========================
# API DEL BUSCADOR
# ==========================
@app.route("/buscar_api", methods=["GET"])
def buscar_api():
    proveedores = []
    busqueda = request.args.get("buscar", "").strip()
    admin_id = request.args.get("admin_id", 1)

    try:
        conexion = conectar_bd()
        cursor = conexion.cursor(dictionary=True, buffered=True)

        if busqueda:
            consulta = """
            SELECT * FROM proveedor
            WHERE (nombre_proveedor LIKE %s
            OR nombre_empresa LIKE %s
            OR descripcion LIKE %s
            OR telefono LIKE %s
            OR correo LIKE %s)
            AND id_usuario = %s
            """
            dato = f"%{busqueda}%"
            cursor.execute(consulta, (dato, dato, dato, dato, dato, admin_id))
            proveedores = cursor.fetchall()

        cursor.close()
    except mysql.connector.Error:
        return jsonify([])
    
    return jsonify(proveedores)


# ==========================
# LOGIN
# ==========================
@app.route("/login")
def login():

    admin = request.args.get("admin", "susana")

    session["ruta_publica"] = admin.lower()

    return render_template("login.html", admin=admin)
# ==========================
# VALIDAR LOGIN
# ==========================
@app.route("/validar_login", methods=["POST"])
def validar_login():

    usuario = request.form["usuario"]

    contrasena = request.form["contrasena"]

    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)

    sql = """
    SELECT *
    FROM usuario
    WHERE nombre_usuario=%s
    AND contrasena=%s
    """

    cursor.execute(sql, (usuario, contrasena))

    datos = cursor.fetchone()

    cursor.close()
    conexion.close()

    if datos:

        session["id_usuario"] = datos["id"]

        session["usuario"] = datos["nombre_usuario"]


        return redirect(url_for("panel"))

    else:

        return "Usuario o contraseña incorrectos."


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
    
    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)
    
    # Filtramos para que Susana o Ceci solo vean lo suyo
    cursor.execute("SELECT * FROM proveedor WHERE id_usuario = %s", (id_admin,))
    mis_provs = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template("proveedores.html", proveedores=mis_provs, usuario=session["usuario"])

# ==========================
# AGREGAR PROVEEDOR
# ==========================
@app.route("/agregar", methods=["GET", "POST"])  # 👈 Cambiado para que coincida con tu panel
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
        
        conexion = conectar_bd()
        cursor = conexion.cursor()
        
        consulta = """
        INSERT INTO proveedor (nombre_proveedor, nombre_empresa, telefono, correo, descripcion, id_usuario)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(consulta, (nombre, empresa, telefono, correo, descripcion, id_admin))
        conexion.commit()
        cursor.close()
        conexion.close()
        
        return redirect(url_for("mis_proveedores")) # Redirige a la función /proveedores
        
    return render_template("agregar.html")

# ==========================
# ✏️ EDITAR PROVEEDOR
# ==========================
@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar_proveedor(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
        
    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)
    
    if request.method == "POST":
        # Capturamos los datos actualizados del formulario
        nombre = request.form.get("nombre")
        empresa = request.form.get("empresa")
        telefono = request.form.get("telefono")
        correo = request.form.get("correo")
        descripcion = request.form.get("descripcion")
        
        # Guardamos los cambios filtrando por el ID del proveedor
        consulta = """
        UPDATE proveedor 
        SET nombre_proveedor=%s, nombre_empresa=%s, telefono=%s, correo=%s, descripcion=%s 
        WHERE id=%s AND id_usuario=%s
        """
        cursor.execute(consulta, (nombre, empresa, telefono, correo, descripcion, id, session["id_usuario"]))
        conexion.commit()
        cursor.close()
        conexion.close()
        return redirect(url_for("mis_proveedores"))
        
    # Si entramos por GET, buscamos los datos actuales para rellenar el formulario
    cursor.execute("SELECT * FROM proveedor WHERE id=%s AND id_usuario=%s", (id, session["id_usuario"]))
    proveedor = cursor.fetchone()
    cursor.close()
    
    if not proveedor:
        return "Proveedor no encontrado o no tienes permisos.", 404
        
    return render_template("editar.html", p=proveedor)


# ==========================
# 🗑️ ELIMINAR PROVEEDOR
# ==========================
@app.route("/eliminar/<int:id>")
def eliminar_proveedor(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
        
    conexion = conectar_bd()
    cursor = conexion.cursor()
    
    # Eliminamos asegurándonos de que pertenezca al usuario logueado por seguridad
    cursor.execute("DELETE FROM proveedor WHERE id=%s AND id_usuario=%s", (id, session["id_usuario"]))
    conexion.commit()
    cursor.close()
    conexion.close()
    
    return redirect(url_for("mis_proveedores"))

# ==========================
# 🔐 CAMBIAR CONTRASEÑA
# ==========================
@app.route("/cambiar_contrasena", methods=["GET", "POST"])
def cambiar_contrasena():
    if "usuario" not in session:
        return redirect(url_for("login"))
        
    error = None
    exito = None
    
    if request.method == "POST":
        actual = request.form.get("actual").strip()
        nueva = request.form.get("nueva").strip()
        confirmar = request.form.get("confirmar").strip()
        id_admin = session["id_usuario"]
        
        conexion = conectar_bd()
        cursor = conexion.cursor(dictionary=True)
        
        # 1. Verificar que la contraseña actual sea correcta
        cursor.execute("SELECT contrasena FROM usuario WHERE id = %s", (id_admin,))
        usuario = cursor.fetchone()
        
        if usuario["contrasena"] != actual:
            error = "La contraseña actual es incorrecta "
        # 2. Verificar que las dos contraseñas nuevas coincidan
        elif nueva != confirmar:
            error = "La nueva contraseña y la confirmación no coinciden "
        # 3. Si todo está bien, actualizamos
        else:
            cursor.execute("UPDATE usuario SET contrasena = %s WHERE id = %s", (nueva, id_admin))
            conexion.commit()
            exito = "¡Contraseña actualizada con éxito! "
            
        cursor.close()
        conexion.close()
        
    return render_template("cambiar_contrasena.html", error=error, exito=exito)


# ==========================
# CERRAR SESIÓN
# ==========================
@app.route("/logout")
def logout():

    print(session)  # Depuración: muestra el contenido de la sesión antes de borrarla

    ruta = session.get("ruta_publica", "susana")

    session.clear()

    return redirect(url_for("inicio", nombre_admin=ruta))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)