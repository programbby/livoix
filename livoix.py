import asyncio
import edge_tts
import pdfplumber
import re
import os
import sys
import time
import logging
from pathlib import Path
from langdetect import detect, LangDetectException, DetectorFactory

# Console Windows : forcer l'UTF-8 (sinon les emojis plantent en cp1252)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

logging.getLogger("pdfminer").setLevel(logging.ERROR)

DetectorFactory.seed = 0

# Voix par défaut selon la langue détectée.
VOIX_PAR_LANGUE = {
    "fr": "fr-FR-RemyMultilingualNeural",
    "en": "en-US-JennyNeural",
    "es": "es-ES-ElviraNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "nl": "nl-NL-FennaNeural",
    "pl": "pl-PL-AgnieszkaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ja": "ja-JP-NanamiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ar": "ar-SA-ZariyahNeural",
}
VOIX_DEFAUT = "fr-FR-RemyMultilingualNeural"

# Voix françaises proposées au menu, de la plus naturelle à la plus plate.
# Les "Multilingual" sont la génération récente : leur intonation varie d'une
# phrase à l'autre, ce qui est exactement ce qui compte sur une heure d'écoute.
VOIX_FR = [
    ("fr-FR-RemyMultilingualNeural",     "Rémy",     "Homme", "France",   "récente, la plus vivante"),
    ("fr-FR-VivienneMultilingualNeural", "Vivienne", "Femme", "France",   "récente, la plus vivante"),
    ("fr-FR-DeniseNeural",               "Denise",   "Femme", "France",   "classique, posée"),
    ("fr-FR-EloiseNeural",               "Éloïse",   "Femme", "France",   "classique, plus jeune"),
    ("fr-FR-HenriNeural",                "Henri",    "Homme", "France",   "classique, plate sur la durée"),
    ("fr-CA-AntoineNeural",              "Antoine",  "Homme", "Québec",   "classique"),
    ("fr-CA-SylvieNeural",               "Sylvie",   "Femme", "Québec",   "classique"),
    ("fr-CA-ThierryNeural",              "Thierry",  "Homme", "Québec",   "classique"),
    ("fr-BE-GerardNeural",               "Gérard",   "Homme", "Belgique", "classique"),
    ("fr-CH-ArianeNeural",               "Ariane",   "Femme", "Suisse",   "classique"),
]

TAILLE_CHUNK = 3000   # signes par segment ; au-delà de ~5000 le service refuse
TENTATIVES = 4        # une coupure réseau ne doit pas gâcher 200 segments déjà faits
MOTS_PAR_MINUTE = 150

FINS_DE_PHRASE = ('.', '!', '?', ':', ';', '»', '"', '…')


def detecter_voix(texte):
    try:
        langue = detect(texte[:2000])
        voix = VOIX_PAR_LANGUE.get(langue, VOIX_DEFAUT)
        print(f"   Langue détectée : {langue} → {voix}")
        return voix
    except LangDetectException:
        print("   Langue non détectée → voix par défaut")
        return VOIX_DEFAUT


def extraire_texte_pdf(chemin_pdf):
    texte = ""
    try:
        with pdfplumber.open(chemin_pdf) as pdf:
            for page in pdf.pages:
                contenu = page.extract_text()
                if contenu:
                    texte += contenu + "\n"
    except Exception as e:
        print(f"❌ Impossible d'ouvrir le PDF : {e}")
        print("   Si le PDF est protégé par mot de passe, retire la protection d'abord.")
        sys.exit(1)
    return texte


def recoller_lignes(texte):
    """Recolle les lignes coupées par la mise en page du PDF.

    Un simple retour à la ligne dans un PDF vient de la largeur de la colonne,
    pas du texte. edge-tts le prononce comme une pause d'une demi-seconde : c'est
    ce qui donne l'impression d'arrêts au hasard au milieu des phrases.

    On garde la coupure dans trois cas seulement : la ligne finit sur une vraie
    ponctuation de fin ; c'est une ligne courte suivie d'une majuscule (un
    titre) ; ou la ligne suivante commence par une puce. Là, la pause est voulue.
    """
    blocs = re.split(r'\n\s*\n', texte)
    sortie = []

    for bloc in blocs:
        lignes = [l.strip() for l in bloc.split('\n') if l.strip()]
        if not lignes:
            continue
        assemble = [lignes[0]]
        for ligne in lignes[1:]:
            precedente = assemble[-1]
            fin_de_phrase = precedente.endswith(FINS_DE_PHRASE)
            titre = len(precedente) < 60 and not fin_de_phrase and ligne[:1].isupper()
            puce = bool(re.match(r'^\s*(?:[•▪◦\-–—*]|\d+\s*[.)°]|[a-z]\))\s+', ligne))
            if fin_de_phrase or titre or puce:
                assemble.append(ligne)
            else:
                assemble[-1] = precedente + ' ' + ligne
        sortie.append('\n'.join(assemble))

    return '\n\n'.join(sortie)


def nettoyer_texte(texte):
    # Réparer les mots coupés en fin de ligne (ex: "impor-\ntant" → "important")
    texte = re.sub(r'-\n([a-zA-ZÀ-ÿ])', r'\1', texte)

    texte = re.sub(r'https?://\S+', '', texte)
    texte = re.sub(r'www\.\S+', '', texte)

    # Lignes de sommaire : de vrais points de remplissage suivis d'un numéro
    texte = re.sub(r'^.{1,80}\.{4,}\s*\d+\s*$', '', texte, flags=re.MULTILINE)

    # Numéros de page seuls, avec variantes : "- 12 -", "Page 12", "12"
    texte = re.sub(r'^\s*[-–]?\s*\d+\s*[-–]?\s*$', '', texte, flags=re.MULTILINE)
    texte = re.sub(r'^\s*[Pp]age\s+\d+.*$', '', texte, flags=re.MULTILINE)

    # Recoller les lignes brisées par la mise en page
    texte = recoller_lignes(texte)

    texte = re.sub(r' {2,}', ' ', texte)
    texte = re.sub(r'\n{3,}', '\n\n', texte)

    return texte.strip()


def diviser_en_chunks(texte, taille_max):
    """Le service refuse les très longs textes : on découpe sur les paragraphes,
    puis sur les phrases si un paragraphe dépasse à lui seul la limite."""
    chunks = []
    chunk_actuel = ""

    for para in texte.split('\n\n'):
        if len(chunk_actuel) + len(para) + 2 < taille_max:
            chunk_actuel += para + "\n\n"
            continue

        if chunk_actuel.strip():
            chunks.append(chunk_actuel.strip())

        if len(para) > taille_max:
            sous_chunk = ""
            for phrase in re.split(r'(?<=[.!?])\s+', para):
                if len(sous_chunk) + len(phrase) < taille_max:
                    sous_chunk += phrase + " "
                else:
                    if sous_chunk.strip():
                        chunks.append(sous_chunk.strip())
                    sous_chunk = phrase + " "
            chunk_actuel = sous_chunk
        else:
            chunk_actuel = para + "\n\n"

    if chunk_actuel.strip():
        chunks.append(chunk_actuel.strip())

    return chunks


async def generer_chunk(texte, fichier_sortie, voix, debit):
    """Réessaie : une coupure réseau au segment 180 sur 200 ne doit pas tout perdre."""
    derniere = None
    for essai in range(1, TENTATIVES + 1):
        try:
            await edge_tts.Communicate(texte, voix, rate=debit).save(fichier_sortie)
            if os.path.getsize(fichier_sortie) > 0:
                return
            raise RuntimeError("fichier vide")
        except Exception as e:
            derniere = e
            if essai < TENTATIVES:
                attente = 2 ** essai
                print(f"\n   ⚠ échec (essai {essai}/{TENTATIVES}) : {e}")
                print(f"   nouvelle tentative dans {attente} s…")
                await asyncio.sleep(attente)
    raise RuntimeError(f"segment abandonné après {TENTATIVES} tentatives : {derniere}")


def duree_lisible(secondes):
    secondes = int(secondes)
    if secondes < 60:
        return f"{secondes} s"
    return f"{secondes // 60} min {secondes % 60:02d} s"


async def pdf_vers_audio(chemin_pdf, dossier_sortie, voix=None, debit="+0%"):
    nom_fichier = Path(chemin_pdf).stem

    print("\n📖 Lecture du PDF...")
    texte = nettoyer_texte(extraire_texte_pdf(chemin_pdf))

    if not texte or len(texte) < 20:
        print("❌ Aucun texte extractible du PDF (probablement un scan/image).")
        print("   Solution : passer un OCR (Adobe Acrobat, Tesseract) avant.")
        sys.exit(1)

    mots = len(texte.split())
    print(f"   {len(texte)} signes — environ {mots} mots → ~{mots / MOTS_PAR_MINUTE:.0f} min d'audio")

    if voix is None:
        voix = detecter_voix(texte)

    fichier_final = os.path.join(dossier_sortie, f"{nom_fichier}.mp3")
    if os.path.exists(fichier_final):
        if input(f"⚠️  {nom_fichier}.mp3 existe déjà. Écraser ? (o/n) : ").lower() != "o":
            print("Annulé.")
            sys.exit(0)

    chunks = diviser_en_chunks(texte, TAILLE_CHUNK)
    print(f"   Découpé en {len(chunks)} segments")
    print(f"   Voix : {voix}   Débit : {debit}\n")

    depart = time.time()
    fichiers_temp = []
    try:
        for i, chunk in enumerate(chunks):
            fichier_temp = os.path.join(dossier_sortie, f"_temp_{i:04d}.mp3")
            reste = ((time.time() - depart) / i * (len(chunks) - i)) if i else 0
            eta = f"   reste ~{duree_lisible(reste)}" if i else ""
            print(f"🔊 Segment {i + 1}/{len(chunks)}{eta}          ", end="\r")
            await generer_chunk(chunk, fichier_temp, voix, debit)
            fichiers_temp.append(fichier_temp)

        print("\n🔗 Assemblage du fichier final...")
        with open(fichier_final, 'wb') as sortie:
            for f in fichiers_temp:
                with open(f, 'rb') as partie:
                    sortie.write(partie.read())
    finally:
        # Même en cas d'échec, on ne laisse pas des dizaines de _temp_ derrière.
        for f in fichiers_temp:
            try:
                os.remove(f)
            except OSError:
                pass

    taille_mb = os.path.getsize(fichier_final) / (1024 * 1024)
    print(f"✅ Terminé en {duree_lisible(time.time() - depart)}")
    print(f"   {fichier_final}")
    print(f"   Taille : {taille_mb:.1f} MB")


def choisir_voix():
    print("\n🎙  Choisis une voix française :\n")
    for n, (ident, nom, genre, pays, note) in enumerate(VOIX_FR, 1):
        defaut = "   ← défaut" if ident == VOIX_DEFAUT else ""
        print(f"  {n:>2}. {nom:<9} {genre:<6} {pays:<9} {note}{defaut}")
    print("\n   Entrée = détecter la langue automatiquement")
    reponse = input("Numéro : ").strip()
    if not reponse:
        return None
    try:
        n = int(reponse)
        if 1 <= n <= len(VOIX_FR):
            return VOIX_FR[n - 1][0]
    except ValueError:
        pass
    print("   Choix non reconnu → détection automatique.")
    return None


def lire_arguments(argv):
    """Retourne (chemin_pdf, voix, debit, menu). Les options peuvent être omises."""
    chemin, voix, debit, menu = None, None, "+0%", False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--voix" and i + 1 < len(argv):
            v = argv[i + 1]
            voix = VOIX_FR[int(v) - 1][0] if v.isdigit() and 1 <= int(v) <= len(VOIX_FR) else v
            i += 2
        elif a == "--debit" and i + 1 < len(argv):
            d = argv[i + 1]
            debit = d if d.endswith("%") else f"{int(d):+d}%"
            i += 2
        elif a == "--menu":
            menu = True
            i += 1
        elif chemin is None:
            chemin = a
            i += 1
        else:
            i += 1
    return chemin, voix, debit, menu


if __name__ == "__main__":
    chemin_pdf, voix_choisie, debit_choisi, menu = lire_arguments(sys.argv[1:])

    if not chemin_pdf:
        print("Usage: python livoix.py <chemin_vers_ton_pdf> [--voix N] [--debit +15%] [--menu]")
        print("\nSans --voix, la langue du livre est détectée et la voix choisie automatiquement.")
        print("\nVoix françaises :")
        for n, (ident, nom, genre, pays, note) in enumerate(VOIX_FR, 1):
            print(f"  {n:>2}. {nom:<9} {genre:<6} {pays:<9} {ident}")
        sys.exit(1)

    if not os.path.exists(chemin_pdf):
        print(f"Erreur : fichier introuvable → {chemin_pdf}")
        sys.exit(1)

    if menu and voix_choisie is None:
        voix_choisie = choisir_voix()

    # Le MP3 est écrit à côté du PDF
    dossier_audio = str(Path(chemin_pdf).resolve().parent)

    try:
        asyncio.run(pdf_vers_audio(chemin_pdf, dossier_audio, voix_choisie, debit_choisi))
    except KeyboardInterrupt:
        print("\n\nInterrompu.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ {e}")
        sys.exit(1)
