import asyncio
import edge_tts
import pdfplumber
import re
import os
import sys
import time
import shutil
import hashlib
import logging
import tempfile
import subprocess
import collections
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


def extraire_pages(chemin_pdf):
    try:
        with pdfplumber.open(chemin_pdf) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages]
    except Exception as e:
        print(f"❌ Impossible d'ouvrir le PDF : {e}")
        print("   Si le PDF est protégé par mot de passe, retire la protection d'abord.")
        sys.exit(1)


TITRES_SOMMAIRE = ("sommaire", "table des matieres", "table des matières", "contents")

DEBUTS_DE_SECTION = re.compile(
    r'^(chapitre|annexe|partie|introduction|avant-propos|préface|conclusion|épilogue'
    r'|première|deuxième|troisième|quatrième|cinquième|sixième|septième|huitième'
    r'|neuvième|dixième|onzième|douzième)\b',
    re.IGNORECASE)


def est_page_de_garde(texte):
    """Page de copyright : ISBN, mentions légales, adresse de l'éditeur.
    Lue à voix haute, ça ne donne que du bruit."""
    if len(texte) > 1200:
        return False
    marqueurs = ('isbn', 'tous droits', 'dépôt légal', 'depot legal', '©',
                 'all rights reserved', 'imprimé en', 'achevé d\'imprimer')
    bas = texte.lower()
    return sum(m in bas for m in marqueurs) >= 2


def est_page_de_sommaire(texte):
    lignes = [l.strip() for l in texte.split('\n') if l.strip()]
    if not lignes:
        return False
    if lignes[0].lower().strip(' :').rstrip('s') in [t.rstrip('s') for t in TITRES_SOMMAIRE]:
        return True
    if len(lignes) < 4:
        return False
    entrees = sum(
        bool(DEBUTS_DE_SECTION.match(l) or re.search(r'\.{3,}\s*\d+$', l))
        for l in lignes)
    return entrees / len(lignes) >= 0.5


def lignes_recurrentes(pages):
    """Les en-têtes et pieds de page reviennent sur des dizaines de pages.
    On repère ceux qui apparaissent sur au moins un quart du livre."""
    if len(pages) < 12:
        return set()
    compte = collections.Counter()
    for t in pages:
        for l in {x.strip() for x in t.split('\n') if 0 < len(x.strip()) <= 80}:
            compte[l] += 1
    seuil = max(4, len(pages) // 4)
    return {l for l, n in compte.items() if n >= seuil}


def assembler_livre(pages, bavard=True):
    """Enchaîne les pages en retirant ce qui n'a pas à être lu."""
    recurrentes = lignes_recurrentes(pages)
    retires = {'garde': 0, 'sommaire': 0, 'recurrentes': 0}

    debut = 0
    dans_le_sommaire = False
    for i, texte in enumerate(pages):
        # Les pages blanches du début ne doivent pas arrêter l'inspection :
        # la page de copyright arrive souvent après une ou deux d'entre elles.
        if not texte.strip():
            debut = i + 1
            continue
        if est_page_de_garde(texte):
            retires['garde'] += 1
            debut = i + 1
            continue
        if est_page_de_sommaire(texte):
            dans_le_sommaire = True
            retires['sommaire'] += 1
            debut = i + 1
            continue
        if dans_le_sommaire:
            # Le sommaire déborde souvent sur des pages courtes ou presque vides.
            if len(texte.strip()) < 250:
                retires['sommaire'] += 1
                debut = i + 1
                continue
            dans_le_sommaire = False
        break

    morceaux = []
    sommaire_precedent = False
    for texte in pages[debut:]:
        if not texte.strip():
            continue
        if est_page_de_sommaire(texte):
            retires['sommaire'] += 1
            sommaire_precedent = True
            continue
        # Un sommaire se termine presque toujours par une page très courte
        # (les dernières annexes). Elle suit une page de sommaire : on la retire.
        if sommaire_precedent and len(texte.strip()) < 250:
            retires['sommaire'] += 1
            continue
        sommaire_precedent = False
        if recurrentes:
            gardees = []
            for l in texte.split('\n'):
                if l.strip() in recurrentes:
                    retires['recurrentes'] += 1
                else:
                    gardees.append(l)
            texte = '\n'.join(gardees)
        morceaux.append(texte)

    if bavard:
        details = []
        if retires['garde']:
            details.append(f"{retires['garde']} page(s) de copyright")
        if retires['sommaire']:
            details.append(f"{retires['sommaire']} page(s) de sommaire")
        if retires['recurrentes']:
            details.append(f"{retires['recurrentes']} en-tête(s)/pied(s) répétés")
        if details:
            print("   Retiré : " + ", ".join(details))

    return "\n".join(morceaux)


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


SYMBOLES_MATHS = '∑∫∏√±≤≥≠∞∈∉⊂⊃∪∩∂∇'


def part_repetee(mot):
    """Part des caractères appartenant à une suite d'au moins 3 identiques.

    Certains PDF dessinent leur filigrane en superposant quatre fois chaque
    glyphe. À l'extraction ça donne « IIIInnnnssssttttiiiittttuuuutttt », que la
    voix ânonne lettre par lettre. Le texte normal ne fait jamais ça.
    """
    if not mot:
        return 0.0
    total = i = 0
    while i < len(mot):
        j = i
        while j + 1 < len(mot) and mot[j + 1] == mot[i]:
            j += 1
        longueur = j - i + 1
        if longueur >= 3:
            total += longueur
        i = j + 1
    return total / len(mot)


def mot_est_filigrane(mot):
    # Cinq caractères minimum : sinon on mangerait les chiffres romains
    # (III, VIII) qui sont du vrai texte.
    if len(mot) >= 5 and part_repetee(mot) >= 0.5:
        return True
    # Suites de ponctuation répétée laissées par le filigrane : )))) ,,,, ::::
    if len(mot) >= 3 and part_repetee(mot) == 1.0 and not any(c.isalnum() for c in mot):
        return True
    return False


def retirer_filigrane(ligne):
    """Retire les mots au glyphe répété, en gardant le reste de la ligne.

    Le filigrane se retrouve souvent collé à une vraie phrase : jeter la ligne
    entière ferait perdre du texte du livre.
    """
    return ' '.join(m for m in ligne.split() if not mot_est_filigrane(m))


def ligne_est_du_bruit(ligne):
    """Formules mises à plat et suites de symboles : illisibles à voix haute."""
    nue = ligne.strip()
    if not nue:
        return True
    if any(c in SYMBOLES_MATHS for c in nue):
        return True

    jetons = nue.split()
    # Aucun vrai mot dans la ligne : « n n », « I = D D », « i i i i », « =1 i =1 ».
    # Ce sont les indices et dénominateurs d'une formule, éclatés en lignes.
    if len(jetons) >= 2 and not any(sum(c.isalpha() for c in j) >= 3 for j in jetons):
        return True

    if len(jetons) >= 6:
        isoles = sum(1 for j in jetons if len(j) == 1)
        if isoles / len(jetons) >= 0.40:
            return True
    return False


def nettoyer_texte(texte):
    # Glyphes que l'extracteur n'a pas su décoder (puces en police symbole)
    texte = re.sub(r'\(cid:\d+\)', '', texte)
    # Réparer les mots coupés en fin de ligne (ex: "impor-\ntant" → "important")
    texte = re.sub(r'-\n([a-zA-ZÀ-ÿ])', r'\1', texte)

    # Adresses, URL et ISBN : illisibles à voix haute
    texte = re.sub(r'https?://\S+', '', texte)
    texte = re.sub(r'www\.\S+', '', texte)
    texte = re.sub(r'\S+@\S+\.\w+', '', texte)
    texte = re.sub(r'^.*\bISBN\b.*$', '', texte, flags=re.MULTILINE | re.IGNORECASE)

    # Lignes de sommaire : de vrais points de remplissage suivis d'un numéro
    texte = re.sub(r'^.{1,80}\.{4,}\s*\d+\s*$', '', texte, flags=re.MULTILINE)

    # Numéros de page seuls, avec variantes : "- 12 -", "Page 12", "12"
    texte = re.sub(r'^\s*[-–]?\s*\d+\s*[-–]?\s*$', '', texte, flags=re.MULTILINE)
    texte = re.sub(r'^\s*[Pp]age\s+\d+.*$', '', texte, flags=re.MULTILINE)

    # Puces isolées sur leur propre ligne : rien à prononcer
    texte = re.sub(r'^\s*[•▪◦·]\s*$', '', texte, flags=re.MULTILINE)
    texte = re.sub(r'^\s*[•▪◦·]\s+', '', texte, flags=re.MULTILINE)

    # Filigranes, formules, tableaux : ligne par ligne
    gardees = []
    for ligne in texte.split('\n'):
        ligne = retirer_filigrane(ligne)
        nue = ligne.strip()
        if not nue:
            continue
        if ligne_est_du_bruit(nue):
            continue
        # Lignes sans presque aucune lettre : tableaux, index, suites de chiffres
        if len(nue) >= 8:
            lettres = sum(c.isalpha() or c.isspace() for c in nue)
            if lettres / len(nue) < 0.55:
                continue
        gardees.append(ligne)
    texte = '\n'.join(gardees)

    # Recoller les lignes brisées par la mise en page
    texte = recoller_lignes(texte)

    # Suites de points ou de tirets qui traînent
    texte = re.sub(r'\.{4,}', '…', texte)
    texte = re.sub(r'[-–—_]{3,}', ' ', texte)

    # Espace manquante après un deux-points ou un point : "Chapitre III :Les..."
    texte = re.sub(r'([:;,])(?=[A-Za-zÀ-ÿ])', r'\1 ', texte)

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


def dossier_travail(chemin_pdf, voix, debit):
    """Un sous-dossier de %TEMP% propre à ce PDF, cette voix et ce débit.

    Les segments y survivent entre deux lancements : si la génération est
    interrompue, la suivante reprend là où elle s'était arrêtée.
    """
    cle = f"{os.path.abspath(chemin_pdf)}|{voix}|{debit}"
    empreinte = hashlib.sha1(cle.encode()).hexdigest()[:10]
    chemin = os.path.join(tempfile.gettempdir(), "livoix", empreinte)
    os.makedirs(chemin, exist_ok=True)
    return chemin


def trouver_ffmpeg():
    """ffmpeg supprime les silences de jointure entre les segments.
    Sans lui on recolle les octets, ce qui laisse un blanc à chaque raccord."""
    chemin = shutil.which("ffmpeg")
    if chemin:
        return chemin
    # winget installe parfois hors du PATH de la session en cours
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.isdir(base):
        for racine, _, fichiers in os.walk(base):
            if "ffmpeg.exe" in fichiers:
                return os.path.join(racine, "ffmpeg.exe")
    return None


def assembler(fichiers, fichier_final, ffmpeg):
    """Recolle les segments en un seul MP3 continu."""
    if ffmpeg:
        liste = os.path.join(os.path.dirname(fichiers[0]), "liste.txt")
        with open(liste, "w", encoding="utf-8") as f:
            for chemin in fichiers:
                f.write("file '" + chemin.replace("\\", "/").replace("'", "'\\''") + "'\n")
        commande = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", liste,
            "-c:a", "libmp3lame", "-b:a", "48k", "-ar", "24000", "-ac", "1",
            fichier_final,
        ]
        resultat = subprocess.run(commande, capture_output=True, text=True)
        if resultat.returncode == 0 and os.path.getsize(fichier_final) > 0:
            return True
        print(f"\n   ⚠ ffmpeg a échoué, recollage simple : {resultat.stderr.strip()[:200]}")

    with open(fichier_final, "wb") as sortie:
        for chemin in fichiers:
            with open(chemin, "rb") as partie:
                sortie.write(partie.read())
    return False


def duree_lisible(secondes):
    secondes = int(secondes)
    if secondes < 60:
        return f"{secondes} s"
    return f"{secondes // 60} min {secondes % 60:02d} s"


async def pdf_vers_audio(chemin_pdf, dossier_sortie, voix=None, debit="+0%"):
    nom_fichier = Path(chemin_pdf).stem

    print("\n📖 Lecture du PDF...")
    pages = extraire_pages(chemin_pdf)
    print(f"   {len(pages)} pages")
    texte = nettoyer_texte(assembler_livre(pages))

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

    # Les segments intermédiaires vont dans %TEMP%, jamais à côté du PDF : sur un
    # gros livre ce sont des centaines de fichiers, et les voir apparaître dans
    # son dossier donne envie de les supprimer — ce qui casse l'assemblage.
    dossier_temp = dossier_travail(chemin_pdf, voix, debit)

    fichiers_temp = [os.path.join(dossier_temp, f"segment_{i:04d}.mp3")
                     for i in range(len(chunks))]
    deja_faits = sum(1 for f in fichiers_temp
                     if os.path.exists(f) and os.path.getsize(f) > 0)
    if deja_faits:
        print(f"   Reprise : {deja_faits} segment(s) déjà générés, on continue\n")

    depart = time.time()
    faits_ici = 0
    for i, chunk in enumerate(chunks):
        fichier_temp = fichiers_temp[i]
        if os.path.exists(fichier_temp) and os.path.getsize(fichier_temp) > 0:
            continue
        reste = ((time.time() - depart) / faits_ici *
                 (len(chunks) - i)) if faits_ici else 0
        eta = f"   reste ~{duree_lisible(reste)}" if faits_ici else ""
        print(f"🔊 Segment {i + 1}/{len(chunks)}{eta}          ", end="\r")
        await generer_chunk(chunk, fichier_temp, voix, debit)
        faits_ici += 1

    print("\n🔗 Assemblage du fichier final...")
    continu = assembler(fichiers_temp, fichier_final, trouver_ffmpeg())
    if not continu:
        print("   (ffmpeg introuvable : de courts blancs subsistent aux raccords)")

    # Seulement une fois le fichier final écrit : si on échoue avant, les
    # segments restent et le prochain lancement reprend où on en était.
    shutil.rmtree(dossier_temp, ignore_errors=True)

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
