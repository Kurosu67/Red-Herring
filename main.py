import discord
from discord import app_commands
from discord.ext import commands
import os
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask

# -------------------------------
# Fonctions de normalisation pour type et statut
# -------------------------------
def normalize_type(value: str) -> str:
    valid_types = {
        "série": "Série", "serie": "Série",
        "animé": "Animé", "anime": "Animé",
        "webtoon": "Webtoon", "manga": "Manga"
    }
    lower = value.lower().strip()
    return valid_types.get(lower, value.capitalize())

def normalize_status(value: str) -> str:
    valid_statuses = {
        "en cours": "En cours", "à voir": "À voir", "a voir": "À voir",
        "termine": "Terminé", "terminé": "Terminé"
    }
    lower = value.lower().strip()
    return valid_statuses.get(lower, value.capitalize())

# -------------------------------
# Serveur web minimal (pour Railway)
# -------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot liste en ligne !"

def run_web():
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    threading.Thread(target=run_web).start()

# -------------------------------
# Base de données
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Variable DATABASE_URL non définie")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Création de la table si elle n'existe pas
    cur.execute('''
        CREATE TABLE IF NOT EXISTS contents (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            title TEXT,
            content_type TEXT,
            status TEXT,
            rating INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        );
    ''')
    # Ajout de la colonne created_at si manquante (migration)
    cur.execute('''
        ALTER TABLE contents
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
    ''')
    conn.commit()
    cur.close()
    conn.close()

# -------------------------------
# Emojis pour l'affichage
# -------------------------------
TYPE_EMOJIS = {"Série": "📺", "Animé": "🎥", "Webtoon": "📱", "Manga": "📚"}
STATUS_EMOJIS = {"En cours": "⏳", "À voir": "👀", "Terminé": "✅"}

# -------------------------------
# Configuration du bot
# -------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    init_db()
    print(f"{bot.user} connecté.")
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Erreur sync commands:", e)

# -------------------------------
# Commande /liste avec pagination et filtres
# -------------------------------
class ListingView(discord.ui.View):
    def __init__(self, rows, build_embed, page_size=10):
        super().__init__(timeout=None)
        self.rows = rows
        self.filtered = rows
        self.build_embed = build_embed
        self.page = 0
        self.size = page_size

        # Dropdown pour type
        options_type = [discord.SelectOption(label="Toutes", value="all")] + [
            discord.SelectOption(label=t, value=t) for t in TYPE_EMOJIS.keys()
        ]
        self.type_select = discord.ui.Select(placeholder="Catégorie", options=options_type)
        self.add_item(self.type_select)

        # Dropdown pour statut
        options_status = [discord.SelectOption(label="Tous", value="all")] + [
            discord.SelectOption(label=s, value=s) for s in STATUS_EMOJIS.keys()
        ]
        self.status_select = discord.ui.Select(placeholder="Statut", options=options_status)
        self.add_item(self.status_select)

    @discord.ui.select()
    async def type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        sel = select.values[0]
        self.filtered = [r for r in self.rows if sel == "all" or r['content_type'] == sel]
        self.page = 0
        await self._update(interaction)

    @discord.ui.select()
    async def status_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        sel = select.values[0]
        self.filtered = [r for r in self.rows if sel == "all" or r['status'] == sel]
        self.page = 0
        await self._update(interaction)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await self._update(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * self.size < len(self.filtered):
            self.page += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        start = self.page * self.size
        end = start + self.size
        embed = self.build_embed(self.filtered[start:end], len(self.filtered))
        await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name="liste", description="Afficher la liste (interactive)")
@app_commands.describe(tri="Mode de tri: alpha|date", notes="Afficher seulement les notés ?")
async def liste(interaction: discord.Interaction, tri: str = None, notes: bool = False):
    # Récupération
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM contents WHERE user_id=%s", (str(interaction.user.id),))
    rows = cur.fetchall()
    cur.close(); conn.close()

    # Tri
    if tri == "alpha":
        rows.sort(key=lambda r: r['title'].lower())
    elif tri == "date":
        rows.sort(key=lambda r: r.get('created_at'), reverse=True)

    # Mode notes
    if notes:
        rated = [r for r in rows if r['rating'] is not None]
        rated.sort(key=lambda r: (-r['rating'], r['title']))
        embed = discord.Embed(title=f"Top notés de {interaction.user.display_name}", color=0x3498db)
        dense = 0; prev = None
        for r in rated:
            if r['rating'] != prev:
                dense += 1
            prev = r['rating']
            rank = {1:'🏆 Top 1', 2:'🥈 Top 2', 3:'🥉 Top 3'}.get(dense, f"#{dense}")
            embed.add_field(
                name=f"{rank} {r['title']} (# {r['id']})",
                value=f"| **{r['rating']}/10**",
                inline=False
            )
            if dense == 3:
                embed.add_field(name="───────────", value='\u200b', inline=False)
        embed.set_footer(text=f"Total notés: {len(rated)}")
        await interaction.response.send_message(embed=embed)
        return

    # Construction de pages
    def build_embed(page_rows, total_count):
        emb = discord.Embed(title=f"Liste de {interaction.user.display_name}", color=0x3498db)
        last_type = None
        for r in page_rows:
            if r['content_type'] != last_type:
                emb.add_field(name=f"─── {r['content_type']} {TYPE_EMOJIS.get(r['content_type'],'')} ───", value='\u200b', inline=False)
                last_type = r['content_type']
            note = f" | **{r['rating']}/10**" if r['rating'] is not None else ''
            emb.add_field(
                name=f"{STATUS_EMOJIS.get(r['status'],'')} {r['title']} (# {r['id']})",
                value=note,
                inline=False
            )
        emb.set_footer(text=f"Total: {total_count} contenus")
        return emb

    view = ListingView(rows, build_embed)
    embed_start = build_embed(rows[:10], len(rows))
    await interaction.response.send_message(embed=embed_start, view=view)

# -------------------------------
# Commande /rechercher
# -------------------------------
@bot.tree.command(name="rechercher", description="Trouver un contenu par titre")
@app_commands.describe(texte="Texte dans le titre")
async def rechercher(interaction: discord.Interaction, texte: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "SELECT * FROM contents WHERE user_id=%s AND title ILIKE %s ORDER BY title LIMIT 10",
        (str(interaction.user.id), f"%{texte}%")
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        return await interaction.response.send_message("Aucun contenu trouvé.", ephemeral=True)
    emb = discord.Embed(title="Résultats de recherche", color=0x3498db)
    for r in rows:
        emb.add_field(
            name=f"{r['title']} (# {r['id']})",
            value=f"{r['status']} {STATUS_EMOJIS.get(r['status'],'')} | {r['content_type']} {TYPE_EMOJIS.get(r['content_type'],'')}",
            inline=False
        )
    await interaction.response.send_message(embed=emb)

# -------------------------------
# Lancement du bot
# -------------------------------
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
