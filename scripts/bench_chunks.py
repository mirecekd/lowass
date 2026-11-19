# scripts/bench_chunks.py
"""Retrieval quality vs. chunk size on a synthetic mixed cs/en/de meeting, with the REAL Cohere embeddings.
Usage: python scripts/bench_chunks.py [words ...]   (default: 180 90 60 40 25)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lowass.config import load
from lowass.embed import Embedder

# (speaker, line). The facts the questions ask for are marked in FACTS below.
LINES = [
    ("Protistrana", "Dobrý den všem, začneme sprint review pro projekt Atlas, máme na to hodinu."),
    ("Ja", "Ahoj, jsem tady, můžeme začít, sdílení obrazovky mám připravené."),
    ("Protistrana", "První bod je migrace Neptune databáze, navrhuji sobotu v noci, protože v neděli je nízký provoz."),
    ("Ja", "Sobota v noci je v pořádku, zálohu zajistí Petr a rollback plán připravím já do pátku."),
    ("Protistrana", "The firewall rules for the new subnet must be approved by security before the go-live."),
    ("Ja", "Understood, I will send the change request to the security team today, they usually answer within two days."),
    ("Protistrana", "Der Rollout in Wien ist für den vierzehnten Dezember geplant, die Kollegen aus Österreich sind informiert."),
    ("Ja", "Gut, dann brauchen wir die Freigabe vom Kunden bis spätestens Freitag der vorigen Woche."),
    ("Protistrana", "Rozpočet na upgrade je jeden milion dvě stě padesát tisíc korun a deadline je dvacátého prosince."),
    ("Ja", "To je v rámci schváleného limitu, fakturace půjde přes projekt ONG a vystavíme ji po akceptaci."),
    ("Protistrana", "What about the monitoring? We need CloudWatch alarms on the replication lag of the Neptune cluster."),
    ("Ja", "Yes, the alarm threshold will be thirty seconds of lag, and it pages the on-call engineer through PagerDuty."),
    ("Protistrana", "Další téma je přechod na CIS benchmark verze sedm, který chce zákazník mít v landing zone do konce března."),
    ("Ja", "Hardening přes Terraform už máme rozpracovaný, zbývá ověřit pravidla pro S3 a CloudTrail."),
    ("Protistrana", "Die Kosten für die Testumgebung liegen bei etwa vierhundert Euro im Monat, das ist noch im Rahmen."),
    ("Ja", "Dobře, testovací prostředí vypneme o víkendu, tím ušetříme zhruba třetinu."),
    ("Protistrana", "Kdo bude na produkci při nasazení hlídat logy? Potřebujeme jednoho člověka přes celou noc."),
    ("Ja", "Logy bude hlídat Martina, má pohotovost a přístup do produkčního účtu přes SSO."),
    ("Protistrana", "Please remember that the VPN certificate expires on the ninth of January and must be renewed before that."),
    ("Ja", "Noted, I will create a ticket for the certificate renewal and assign it to the network team."),
    ("Protistrana", "Poslední věc, školení pro operátory proběhne v úterý ve dvě odpoledne v místnosti na Karlově náměstí."),
    ("Ja", "Výborně, pozvánku rozešlu ještě dnes, děkuji všem za účast a končíme."),
]
# question -> a word that must be in the retrieved chunk to count as a hit
FACTS = [
    ("kdy se bude migrovat Neptune databáze", "sobotu"),
    ("kdo zajistí zálohu před migrací", "Petr"),
    ("who must approve the firewall rules", "security"),
    ("wann ist der Rollout in Wien", "vierzehnten"),
    ("kolik stojí upgrade a jaký je deadline", "milion"),
    ("what is the alarm threshold for replication lag", "thirty"),
    ("do kdy musí být CIS benchmark v landing zone", "března"),
    ("wie hoch sind die Kosten der Testumgebung", "vierhundert"),
    ("kdo hlídá logy při nasazení", "Martina"),
    ("when does the VPN certificate expire", "ninth"),
    ("kdy a kde je školení operátorů", "Karlově"),
]


FILLER = [
    ("Protistrana", "Ještě k tomu jednu poznámku, ten ticket je pořád otevřený a čeká na vyjádření od týmu."),
    ("Ja", "Ano, souhlasím, ozvu se tam během dne a dám vědět, jak to dopadlo."),
    ("Protistrana", "We should also look at the dashboard again, some of the widgets are loading slowly in the morning."),
    ("Ja", "I think it is the query behind the second panel, I will profile it later this week."),
    ("Protistrana", "Das Protokoll von letzter Woche ist noch nicht versendet worden, wer übernimmt das?"),
    ("Ja", "Kolegyně z projektové kanceláře to rozešle, ať se nepíše znovu, už to existuje."),
    ("Protistrana", "A co ten druhý tým, mají už přístup do staging prostředí, nebo na to pořád čekají?"),
    ("Ja", "Přístup mají od včerejška, jen jim chybí práva k logům, to řeší správce účtu."),
    ("Protistrana", "Okay, and the retrospective will be next Thursday, please add your points to the board before that."),
    ("Ja", "Will do, I already have three items, mostly about the deployment pipeline and flaky tests."),
]


def noisy(n_rounds: int) -> list[tuple[str, str]]:
    """The 22 fact lines spread through a long meeting of unrelated small talk (what a real hour looks like)."""
    out: list[tuple[str, str]] = []
    for i, line in enumerate(LINES):
        out.append(line)
        for j in range(n_rounds):
            out.append(FILLER[(i * 3 + j) % len(FILLER)])
    return out


def chunk_lines(lines: list[tuple[str, str]], words: int) -> list[str]:
    """Same rule as Meeting.transcript_line: flush when the pending lines reach `words` words."""
    out, pending, count = [], [], 0
    for sp, text in lines:
        pending.append(f"{sp}: {text}")
        count += len(f"{sp}: {text}".split())
        if count >= words:
            out.append("\n".join(pending))
            pending, count = [], 0
    if pending:
        out.append("\n".join(pending))
    return out


def run(words: int, emb: Embedder, lines: list[tuple[str, str]], qvec: np.ndarray) -> tuple[int, int, int, int, int]:
    chunks = chunk_lines(lines, words)
    cv = emb.embed(chunks)  # ONE batched call per configuration
    cv = cv / np.linalg.norm(cv, axis=1, keepdims=True)
    top1 = top3 = top5 = 0
    for (_q, needle), qv in zip(FACTS, qvec, strict=True):
        order = np.argsort(-(cv @ (qv / np.linalg.norm(qv))))[:5]  # the agent tool reads 5 hits by default
        top1 += needle.lower() in chunks[order[0]].lower()
        top3 += any(needle.lower() in chunks[i].lower() for i in order[:3])
        top5 += any(needle.lower() in chunks[i].lower() for i in order)
    return len(chunks), int(top1), int(top3), int(top5), len(FACTS)


def main() -> None:
    cfg = load()
    e = cfg.section("embeddings")
    emb = Embedder(cfg.env("LITELLM_BASE_URL"), cfg.env("LITELLM_API_KEY"), e["model"], int(e.get("dimensions", 1536)))
    qvec = emb.embed([q for q, _n in FACTS], "search_query")  # the questions are embedded once
    sizes = [int(a) for a in sys.argv[1:]] or [180, 90, 60, 40, 25]
    for rounds in (0, 3, 6):
        lines = noisy(rounds)
        total = sum(len(f"{s}: {t}".split()) for s, t in lines)
        print(f"\n{len(lines)} lines, {total} words, {len(FACTS)} questions (filler lines per fact line: {rounds})")
        print(f"{'chunk_words':>11} {'chunks':>7} {'top1':>6} {'top3':>6} {'top5':>6}", flush=True)
        for w in sizes:
            chunks, t1, t3, t5, n = run(w, emb, lines, qvec)
            print(f"{w:>11} {chunks:>7} {t1:>3}/{n} {t3:>3}/{n} {t5:>3}/{n}", flush=True)


main()
