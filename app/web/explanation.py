"""Content for the /uitleg (Explanation) page.

Each metric is described by three fields the user asked for:
  what      — what it is / how it is computed
  does      — what it does / why it matters
  develops  — how it is expected to change during the day

The text is written against the actual implementations (recovery.py,
strain.py, fitness.py, sync.py) so it stays accurate when the numbers
change — it never re-derives anything, it only explains.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    name: str
    what: str
    does: str
    develops: str
    range: str = ""


@dataclass(frozen=True)
class Section:
    title: str
    metrics: list[Metric]


SECTIONS: list[Section] = [
    Section(
        "Kernmetrieken",
        [
            Metric(
                name="Herstel",
                range="0–100",
                what=(
                    "Gewogen score van je herstel over de nacht, Whoop-stijl. "
                    "Primaire factor is HRV (ln RMSSD z-score t.o.v. een 60-daagse "
                    "basislijn); op de Venu 2 (geen HRV) weegt de engine over "
                    "RHR-afwijking, slaapkwaliteit en stress."
                ),
                does=(
                    "Vertelt of je lichaam klaar is voor een zware training of beter "
                    "rust. Banden: groen ≥66, geel 34–65, rood <34."
                ),
                develops=(
                    "Stijgt na rust en goede slaap, daalt na zware training, alcohol, "
                    "ziekte of slechte slaap. Normaal schommelt het per dag; een rode "
                    "dag betekent rustig aan of rusten."
                ),
            ),
            Metric(
                name="Strain",
                range="0–21",
                what=(
                    "Dagelijkse trainingsbelasting, gekalibreerd op je eigen historie: "
                    "≈20 staat voor je zwaarste dag in de afgelopen 90 dagen. Berekend "
                    "uit TRIMP / Edwards zone-minuten; krachttraining telt op basis van "
                    "duur."
                ),
                does=(
                    "Kwantificeert hoeveel belasting een dag op je lichaam legde. "
                    "Voedt de vermoeidheidsmaat (ATL) die je herstel beïnvloedt."
                ),
                develops=(
                    "0 op rustdagen, hoog na een zware sessie. Een zware dag verhoogt "
                    "direct je strain; de invloed op vermoeidheid bouwt zich over de "
                    "volgende dagen op."
                ),
            ),
            Metric(
                name="Slaap",
                range="0–100 + duur",
                what=(
                    "Garmins eigen slaapscore plus duur en stadia (diep, REM, licht, "
                    "waak). De duur wordt ook in uren getoond."
                ),
                does=(
                    "Slaap is de belangrijkste herstelaanjager — hij weegt zwaar mee "
                    "in je herstelscore."
                ),
                develops=(
                    "Hoger bij een consistent slaapritme, lager na late avonden of "
                    "alcohol. Diepe slaap komt vooral vroeg in de nacht, REM later."
                ),
            ),
            Metric(
                name="RHR (rusthartslag)",
                range="bpm",
                what="Hartslag in rust, 's nachts gemeten door de Venu 2.",
                does=(
                    "Een hogere RHR dan normaal wijst vaak op vermoeidheid, stress, "
                    "ziekte of slecht herstel; een lagere RHR wijst op beter herstel "
                    "en fitheid."
                ),
                develops=(
                    "Stijgt na zware training of alcohol, daalt na rustdagen en bij "
                    "betere conditie. Vergelijk altijd met je eigen basislijn."
                ),
            ),
            Metric(
                name="TSB (Training Stress Balance)",
                range="±",
                what=(
                    "CTL (fitheid, 42-daags gemiddelde) − ATL (vermoeidheid, 7-daags "
                    "gemiddelde) van je strain."
                ),
                does=(
                    "Positief = fris, negatief = vermoeid. Geeft aan of je opbouwt of "
                    "juist herstelt van trainingsbelasting."
                ),
                develops=(
                    "Daalt tijdens zware trainingsweken, stijgt tijdens rust. Sterk "
                    "negatief betekent opgebouwde vermoeidheid → rustigere dagen "
                    "inplannen."
                ),
            ),
        ],
    ),
    Section(
        "Garmin-native metingen",
        [
            Metric(
                name="Stress",
                range="0–100",
                what="Garmins stressscore, afgeleid van hartslagvariatie gedurende de dag.",
                does=(
                    "Hoge stress in combinatie met laag herstel is een risicosignaal "
                    "voor overtraining."
                ),
                develops=(
                    "Piekt op drukke of stressvolle dagen en bij ziekte; laag tijdens "
                    "rust en slaap."
                ),
            ),
            Metric(
                name="Body Battery",
                range="0–100",
                what="Garmins eigen energiemeter op basis van HRV, stress en activiteit.",
                does="Schat je energiereserve voor de dag.",
                develops=(
                    "Laag bij het wakker worden na slechte slaap, laadt op tijdens "
                    "rust en daalt bij inspanning."
                ),
            ),
            Metric(
                name="VO₂max",
                range="ml/kg/min",
                what="Schatting van je aerobe conditie, berekend door Garmin.",
                does="Geeft je trainingsniveau aan en hoe het zich ontwikkelt.",
                develops=(
                    "Verandert langzaam over weken tot maanden, niet per dag. "
                    "Consistente training laat het geleidelijk stijgen."
                ),
            ),
            Metric(
                name="HRV (hartslagvariatie)",
                range="—",
                what=(
                    "Variatie tussen opeenvolgende hartslagen, 's nachts. De Venu 2 "
                    "levert dit niet."
                ),
                does=(
                    "Hoge HRV = goed herstel. Wanneer beschikbaar is het de primaire "
                    "herstelfactor; zonder HRV valt de engine terug op RHR, slaap en "
                    "stress."
                ),
                develops=(
                    "Op de Venu 2 wordt HRV niet getoond — herstel wordt dan "
                    "herberekend over de beschikbare factoren."
                ),
            ),
        ],
    ),
    Section(
        "Dagboek, inzichten en coach",
        [
            Metric(
                name="Dagboek",
                range="11 factoren",
                what=(
                    "Dagelijkse leefstijlfactoren: alcohol, cafeïne laat, laat gegeten, "
                    "hoge stress, scherm laat, spierpijn, ziekte, sauna, magnesium, laat "
                    "gewerkt en stretchen."
                ),
                does=(
                    "Legt het verband tussen je leefstijl en je herstel/slaap, zodat de "
                    "inzichtenpagina kan laten zien wat voor jou werkt."
                ),
                develops=(
                    "Log 1–3 factoren per dag via Signal (de herinnering vraagt er "
                    "maximaal 3) of vul alles in op deze pagina."
                ),
            ),
            Metric(
                name="Inzichten",
                range="gecorreleerd",
                what=(
                    "Verbanden tussen dagboekfactoren en je herstel/slaap, alleen "
                    "getoond als er genoeg data is (≥5 dagen mét én zonder de factor)."
                ),
                does=(
                    "Vertelt welke leefstijlkeuzes voor jou meetbaar uitmaken, met "
                    "richting en effectgrootte."
                ),
                develops=(
                    "Verschijnt pas na ~2 weken consequent loggen — de engine weigert "
                    "onderbouwde claims te tonen zolang de steekproef te klein is."
                ),
            ),
            Metric(
                name="Coach",
                range="opt-in",
                what=(
                    "LLM-coach die je vragen beantwoordt over je eigen data (via "
                    "/coach of Signal /ask)."
                ),
                does=(
                    "Geeft uitleg en advies, uitsluitend op basis van cijfers die "
                    "werkelijk in je data staan — verzonnen metriek wordt nooit "
                    "doorgegeven."
                ),
                develops=(
                    "Altijd beschikbaar zodra LLM_ENABLED is ingeschakeld; de "
                    "antwoorden volgen je meest recente herstel en training."
                ),
            ),
        ],
    ),
]


def build_context() -> dict:
    return {"sections": SECTIONS}
