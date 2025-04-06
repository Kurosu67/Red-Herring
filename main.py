import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import threading
from flask import Flask

# ===============================
# Section : Serveur web minimal
# ===============================

app = Flask(__name__)

@app.route("/")
def home():
    return "Le bot est en ligne !"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.start()

# ===============================
# Section : Initialisation de la DB
# ===============================

# Dictionnaires d'emojis pour une meilleure lisibilité
TYPE_EMOJIS = {
    "Série": "📺",
    "Animé": "🎥",
    "Webtoon": "📱",
    "Manga": "📚"
}

STATUS_EMOJIS = {
    "En cours": "⏳",
    "À voir": "👀",
    "Terminé": "✅"
}

# Chemin vers la base de données SQLite
DB_PATH = 'contents.db'

def init_db():
    """
    Initialise la base de données en créant la table 'contents' si elle n'existe pas.
    La table inclut un champ 'rating' pour la note sur 10.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            title TEXT,
            content_type TEXT,
            status TEXT,
            rating INTEGER
        )
    ''')
    conn.commit()
    conn.close()

# ===============================
# Section : Configuration du bot
# ===============================

# Récupérer le token du bot depuis les variables d'environnement
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN is None:
    raise Exception("Le token Discord n'a pas été défini dans les variables d'environnement.")

# Configuration des intents pour le bot
intents = discord.Intents.default()
intents.message_content = True  # Nécessaire pour lire le contenu des messages

# Création du bot
bot = commands.Bot(command_prefix="!", intents=intents)

# ===============================
# Section : Vues interactives (UI)
# ===============================

class AddContentView(discord.ui.View):
    """
    Vue interactive pour ajouter un contenu (ou plusieurs) via des menus déroulants.
    """
    def __init__(self, user_id, title, multiple=False, titles=None):
        super().__init__()
        self.user_id = user_id
        self.title = title      # Titre pour un ajout simple
        self.titles = titles    # Liste de titres pour un ajout multiple
        self.multiple = multiple
        self.selected_type = None
        self.selected_status = None

    @discord.ui.select(
        placeholder="Sélectionne le type de contenu",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Série", description="Ajouter une série"),
            discord.SelectOption(label="Animé", description="Ajouter un animé"),
            discord.SelectOption(label="Webtoon", description="Ajouter un webtoon"),
            discord.SelectOption(label="Manga", description="Ajouter un manga")
        ]
    )
    async def select_type(self, select: discord.ui.Select, interaction: discord.Interaction):
        self.selected_type = select.values[0]
        await interaction.response.send_message(
            f"Type sélectionné : **{self.selected_type} {TYPE_EMOJIS.get(self.selected_type, '')}**", 
            ephemeral=True
        )

    @discord.ui.select(
        placeholder="Sélectionne le statut",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="En cours", description="En cours de visionnage/lecture"),
            discord.SelectOption(label="À voir", description="À voir/à lire"),
            discord.SelectOption(label="Terminé", description="Contenu terminé")
        ]
    )
    async def select_status(self, select: discord.ui.Select, interaction: discord.Interaction):
        self.selected_status = select.values[0]
        await interaction.response.send_message(
            f"Statut sélectionné : **{self.selected_status} {STATUS_EMOJIS.get(self.selected_status, '')}**", 
            ephemeral=True
        )

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.green)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.selected_type is None or self.selected_status is None:
            await interaction.response.send_message("Merci de sélectionner le type et le statut.", ephemeral=True)
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if not self.multiple:
            c.execute("INSERT INTO contents (user_id, title, content_type, status) VALUES (?, ?, ?, ?)",
                      (self.user_id, self.title, self.selected_type, self.selected_status))
        else:
            for t in self.titles:
                t = t.strip()
                if t:
                    c.execute("INSERT INTO contents (user_id, title, content_type, status) VALUES (?, ?, ?, ?)",
                              (self.user_id, t, self.selected_type, self.selected_status))
        conn.commit()
        conn.close()
        await interaction.response.send_message("Contenu(s) ajouté(s) avec succès !", ephemeral=True)
        self.stop()

# ===============================
# Section : Commandes Slash
# ===============================

@bot.tree.command(name="ajouter", description="Ajouter un contenu")
async def ajouter(interaction: discord.Interaction, title: str):
    view = AddContentView(user_id=str(interaction.user.id), title=title)
    await interaction.response.send_message(
        f"Ajout du contenu : **{title}**\nSélectionne le type et le statut :", 
        view=view
    )

@bot.tree.command(name="ajouterplus", description="Ajouter plusieurs contenus")
async def ajouterplus(interaction: discord.Interaction, titles: str):
    title_list = titles.split(',')
    view = AddContentView(user_id=str(interaction.user.id), title=None, multiple=True, titles=title_list)
    titles_clean = ', '.join([t.strip() for t in title_list if t.strip()])
    await interaction.response.send_message(
        f"Ajout de plusieurs contenus : **{titles_clean}**\nSélectionne le type et le statut pour tous :", 
        view=view
    )

@bot.tree.command(name="liste", description="Afficher la liste de contenus d'un utilisateur")
async def liste(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, content_type, status, rating FROM contents WHERE user_id=?", (str(target.id),))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await interaction.response.send_message(f"{target.display_name} n'a aucun contenu dans sa liste.", ephemeral=True)
        return

    embed = discord.Embed(title=f"Liste de contenus de {target.display_name}", color=0x3498db)
    for row in rows:
        entry_id, title, content_type, status, rating = row
        note_str = f" | Note : **{rating}/10**" if rating is not None else ""
        embed.add_field(
            name=f"{title} {TYPE_EMOJIS.get(content_type, '')}",
            value=f"Type : **{content_type}** | Statut : **{status} {STATUS_EMOJIS.get(status, '')}** (ID : {entry_id}){note_str}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="modifier", description="Modifier le statut d'un contenu par ID")
async def modifier(interaction: discord.Interaction, id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT title, content_type, status FROM contents WHERE id=? AND user_id=?", (id, str(interaction.user.id)))
    row = c.fetchone()
    if not row:
        await interaction.response.send_message("Contenu non trouvé ou vous n'êtes pas le propriétaire de ce contenu.", ephemeral=True)
        conn.close()
        return
    title, content_type, current_status = row
    conn.close()

    class ModifierStatusView(discord.ui.View):
        def __init__(self, user_id, content_id):
            super().__init__()
            self.user_id = user_id
            self.content_id = content_id
            self.new_status = None

        @discord.ui.select(
            placeholder="Sélectionne le nouveau statut",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="En cours", description="En cours de visionnage/lecture"),
                discord.SelectOption(label="À voir", description="À voir/à lire"),
                discord.SelectOption(label="Terminé", description="Contenu terminé")
            ]
        )
        async def select_new_status(self, select: discord.ui.Select, interaction: discord.Interaction):
            self.new_status = select.values[0]
            await interaction.response.send_message(
                f"Nouveau statut sélectionné : **{self.new_status} {STATUS_EMOJIS.get(self.new_status, '')}**", 
                ephemeral=True
            )

        @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.green)
        async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
            if self.new_status is None:
                await interaction.response.send_message("Merci de sélectionner un nouveau statut.", ephemeral=True)
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE contents SET status=? WHERE id=? AND user_id=?", (self.new_status, self.content_id, str(interaction.user.id)))
            conn.commit()
            conn.close()
            await interaction.response.send_message("Statut mis à jour avec succès !", ephemeral=True)
            self.stop()

    view = ModifierStatusView(user_id=str(interaction.user.id), content_id=id)
    await interaction.response.send_message(
        f"Modification du statut pour **{title}** (Actuel : {current_status} {STATUS_EMOJIS.get(current_status, '')}). Sélectionne le nouveau statut :", 
        view=view
    )

@bot.tree.command(name="supprimer", description="Supprimer du contenu par type et/ou statut")
@app_commands.describe(
    member="L'utilisateur dont vous voulez supprimer le contenu (par défaut : vous-même)",
    content_type="Filtrer par type de contenu",
    status="Filtrer par statut"
)
@app_commands.choices(content_type=[
    app_commands.Choice(name="Série 📺", value="Série"),
    app_commands.Choice(name="Animé 🎥", value="Animé"),
    app_commands.Choice(name="Webtoon 📱", value="Webtoon"),
    app_commands.Choice(name="Manga 📚", value="Manga")
])
@app_commands.choices(status=[
    app_commands.Choice(name="En cours ⏳", value="En cours"),
    app_commands.Choice(name="À voir 👀", value="À voir"),
    app_commands.Choice(name="Terminé ✅", value="Terminé")
])
async def supprimer(interaction: discord.Interaction, member: discord.Member = None, content_type: str = None, status: str = None):
    target = member or interaction.user

    if target.id != interaction.user.id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Vous ne pouvez supprimer que vos propres contenus.", ephemeral=True)
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT id, title, content_type, status FROM contents WHERE user_id=?"
    params = [str(target.id)]
    if content_type is not None:
        query += " AND content_type=?"
        params.append(content_type)
    if status is not None:
        query += " AND status=?"
        params.append(status)
    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("Aucun contenu correspondant n'a été trouvé.", ephemeral=True)
        return

    class DeleteContentView(discord.ui.View):
        def __init__(self, entries):
            super().__init__()
            self.entries = entries
            self.selected_ids = []
            options = []
            for entry in entries:
                entry_id, title, c_type, c_status = entry
                label = f"{entry_id} - {title}"
                description = f"Type: {c_type} {TYPE_EMOJIS.get(c_type, '')} | Statut: {c_status} {STATUS_EMOJIS.get(c_status, '')}"
                options.append(discord.SelectOption(label=label, value=str(entry_id), description=description))
            self.select = discord.ui.Select(
                placeholder="Sélectionnez les contenus à supprimer", 
                min_values=1, 
                max_values=len(options), 
                options=options
            )
            self.select.callback = self.select_callback
            self.add_item(self.select)

        async def select_callback(self, interaction: discord.Interaction):
            self.selected_ids = self.select.values
            await interaction.response.send_message(f"{len(self.selected_ids)} contenu(s) sélectionné(s) pour suppression.", ephemeral=True)

        @discord.ui.button(label="Confirmer suppression", style=discord.ButtonStyle.red)
        async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
            if not self.selected_ids:
                await interaction.response.send_message("Aucun contenu sélectionné.", ephemeral=True)
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for entry_id in self.selected_ids:
                c.execute("DELETE FROM contents WHERE id=? AND user_id=?", (entry_id, str(target.id)))
            conn.commit()
            conn.close()
            await interaction.response.send_message("Contenu(s) supprimé(s) avec succès.", ephemeral=True)
            self.stop()

    view = DeleteContentView(rows)
    await interaction.response.send_message("Contenus trouvés. Sélectionnez celui(s) à supprimer :", view=view, ephemeral=True)

@bot.tree.command(name="noter", description="Attribuer une note à un contenu (sur 10)")
async def noter(interaction: discord.Interaction, id: int, note: int):
    if note < 0 or note > 10:
        await interaction.response.send_message("La note doit être comprise entre 0 et 10.", ephemeral=True)
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT title FROM contents WHERE id=? AND user_id=?", (id, str(interaction.user.id)))
    row = c.fetchone()
    if not row:
        await interaction.response.send_message("Contenu non trouvé ou vous n'êtes pas le propriétaire de ce contenu.", ephemeral=True)
        conn.close()
        return

    c.execute("UPDATE contents SET rating=? WHERE id=? AND user_id=?", (note, id, str(interaction.user.id)))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"Contenu noté **{note}/10** avec succès !", ephemeral=True)

# ===============================
# Section : Démarrage du bot et du serveur web
# ===============================

@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Synchronisation réussie pour {len(synced)} commande(s).")
    except Exception as e:
        print(e)
    print(f"Bot connecté en tant que {bot.user}")

# Lancer le serveur web minimal (pour Railway) et le bot Discord
keep_alive()
bot.run(TOKEN)
