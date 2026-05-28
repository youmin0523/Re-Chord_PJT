"""One-shot tag retrofit for music_songs.json.

Walks every song record and applies the standardized tag taxonomy
defined in music_songs.json#tag_taxonomy. Idempotent — re-running won't
duplicate tags. Preserves the per-song single-line format so diffs stay
readable.

Heuristics applied:
  1. id-prefix → performed-by:{team-slug}
  2. year ∈ {2024, 2025, 2026} → release-type:single   (single drops)
  3. id contains "live" / title contains "Live" → live-version
  4. id contains "cover" → cover-of:{?}  (only when target known)
  5. existing "korean-worship"/"global-worship" left as-is (descriptive)

Old non-standard tags (way-maker-translation, *-translation, hymn-arrangement
plain, etc.) are preserved unless they map cleanly to the new form.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / "data" / "seed" / "music_songs.json"

# id-prefix → performed-by team slug. Order matters (longest prefix first).
PREFIX_TEAM_MAP: list[tuple[str, str]] = [
    ("markers-2025-", "markers"),
    ("markers-2026-", "markers"),
    ("markers-ministry-", "markers-ministry"),
    ("markers-", "markers"),
    ("anointing-2024-", "anointing"),
    ("anointing-", "anointing"),
    ("welove-revibe-", "welove"),
    ("welove-", "welove"),
    ("jus-arise-shine-", "jus"),
    ("jus-", "jus"),
    ("yeram-2025-", "yeram"),
    ("yeram-", "yeram"),
    ("gifted-", "gifted"),
    ("jesusroad-", "jesusroad"),
    ("sum-worship-", "sum-worship"),
    ("sungrak-church-", "sungrak-church"),
    ("dalbit-", "dalbit-maeul"),
    ("kimbokyu-", "kim-bokyu"),
    ("kim-bokyu-", "kim-bokyu"),
    ("acts-", "acts-worship"),
    ("twin-wings-", "twin-wings"),
    ("qtm-", "qtm"),
    ("agape-worship-", "agapao-worship"),
    ("agapao-worship-", "agapao-worship"),
    ("faith-worship-", "faith-worship"),
    ("hosanna-worship-", "hosanna-worship"),
    ("onnuri-", "onnuri-praise-team"),
    ("bundang-uri-", "bundang-uri-worship"),
    ("sarang-church-", "sarang-church-worship"),
    ("oryun-", "oryun-worship"),
    ("ccc-", "ccc-korea"),
    ("duranno-", "duranno-worship"),
    ("trinity-worship-", "trinity-worship-kr"),
    ("dream-worship-", "dream-worship-kr"),
    ("tru-us-", "tru-us"),
    ("sigwang-", "sigwang"),
    ("park-jiyoung-", "park-jiyoung-worship"),
    ("amazing-grace-korea-", "amazing-grace-korea"),
    ("team-luke-", "team-luke-worship"),
    ("kim-yean-", "kim-yean-translation"),
    ("young-diary-", "young-diary"),
    ("awakening-", "awakening-kr"),
    ("blessing-worship-", "blessing-worship"),
    ("new-worship-team-", "new-worship-team"),
    ("seven-stage-worship-", "seven-stage-worship"),
    ("higher-music-", "higher-music-kr"),
    ("levistance-", "lamp-room"),
    ("dbworship-", "db-worship"),
    ("eum-worship-", "eum-worship"),
    ("fia-worship-", "fia-worship"),
    ("disciples-mission-", "disciples-mission"),
    ("sound-of-eternity-", "sound-of-eternity"),
    ("david-tabernacle-", "david-tabernacle"),
    ("sound-of-praise-", "sound-of-praise-kr"),
    ("ignite-worship-", "ignite-worship-kr"),
    ("pacific-worship-", "pacific-worship-kr"),
    ("ywam-", "ywam"),
    ("newsong-ministry-", "newsong-ministry"),
    ("hillsong-united-", "hillsong-united"),
    ("hillsong-yf-", "hillsong-young-free"),
    ("hillsong-y-and-f-", "hillsong-young-free"),
    ("hillsong-young-free-", "hillsong-young-free"),
    ("hillsong-", "hillsong"),
    ("elevation-", "elevation"),
    ("bethel-", "bethel"),
    ("maverick-", "maverick-city"),
    ("passion-", "passion"),
    ("jesus-culture-", "jesus-culture"),
    ("city-alight-", "city-alight"),
    ("cityalight-", "city-alight"),
    ("vineyard-", "vineyard"),
    ("vertical-", "vertical-worship"),
    ("mosaic-msc-", "mosaic-msc"),
    ("sovereign-grace-", "sovereign-grace"),
    ("we-the-kingdom-", "we-the-kingdom"),
    ("wtk-", "we-the-kingdom"),
    ("ihopkc-", "ihopkc"),
    ("jesus-image-", "jesus-image"),
    ("upperroom-", "upperroom"),
    ("matt-redman-", "matt-redman"),
    ("chris-tomlin-", "chris-tomlin"),
    ("tomlin-", "chris-tomlin"),
    ("kari-jobe-", "kari-jobe"),
    ("phil-wickham-", "phil-wickham"),
    ("crowder-", "crowder"),
    ("david-crowder-band-", "david-crowder-band"),
    ("brandon-lake-", "brandon-lake"),
    ("cory-asbury-", "cory-asbury"),
    ("brian-johnson-", "brian-johnson"),
    ("steffany-gretzinger-", "steffany-gretzinger"),
    ("kim-walker-smith-", "kim-walker-smith"),
    ("torwalt-", "torwalt"),
    ("matt-maher-", "matt-maher"),
    ("tauren-wells-", "tauren-wells"),
    ("zach-williams-", "zach-williams"),
    ("jordan-feliz-", "jordan-feliz"),
    ("cain-", "cain"),
    ("anne-wilson-", "anne-wilson"),
    ("katy-nichole-", "katy-nichole"),
    ("skillet-", "skillet"),
    ("lecrae-", "lecrae"),
    ("tobymac-", "tobymac"),
    ("for-king-and-country-", "for-king-and-country"),
    ("for-king-", "for-king-and-country"),
    ("newsboys-", "newsboys"),
    ("casting-crowns-", "casting-crowns"),
    ("mercyme-", "mercyme"),
    ("sanctus-real-", "sanctus-real"),
    ("lauren-daigle-", "lauren-daigle"),
    ("third-day-", "third-day"),
    ("michael-w-smith-", "michael-w-smith"),
    ("amy-grant-", "amy-grant"),
    ("rich-mullins-", "rich-mullins"),
    ("keith-green-", "keith-green"),
    ("aaron-shust-", "aaron-shust"),
    ("mandisa-", "mandisa"),
    ("needtobreathe-", "needtobreathe"),
    ("switchfoot-", "switchfoot"),
    ("relient-k-", "relient-k"),
    ("nf-", "nf"),
    ("forrest-frank-", "forrest-frank"),
    ("andy-mineo-", "andy-mineo"),
    ("we-are-messengers-", "we-are-messengers"),
    ("hannah-kerr-", "hannah-kerr"),
    ("riley-clemmons-", "riley-clemmons"),
    ("selah-", "selah"),
    ("mark-schultz-", "mark-schultz"),
    ("hollyn-", "hollyn"),
    ("mack-brock-", "mack-brock"),
    ("charity-gayle-", "charity-gayle"),
    ("misty-edwards-", "misty-edwards"),
    ("sean-curran-", "sean-curran"),
    ("pat-barrett-", "pat-barrett"),
    ("sean-feucht-", "sean-feucht"),
    ("brian-doerksen-", "brian-doerksen"),
    ("brenton-brown-", "brenton-brown"),
    ("israel-houghton-", "israel-houghton"),
    ("paul-baloche-", "paul-baloche"),
    ("tim-hughes-", "tim-hughes"),
    ("robin-mark-", "robin-mark"),
    ("delirious-", "delirious"),
    ("darrell-evans-", "darrell-evans"),
    ("don-moen-", "don-moen"),
    ("ron-kenoly-", "ron-kenoly"),
    ("lincoln-brewster-", "lincoln-brewster"),
    ("travis-greene-", "travis-greene"),
    ("tasha-cobbs-", "tasha-cobbs"),
    ("sinach-", "sinach"),
    ("john-mark-mcmillan-", "john-mark-mcmillan"),
    ("brooke-ligertwood-", "brooke-ligertwood"),
    ("all-sons-and-daughters-", "all-sons-and-daughters"),
    ("doe-", "doe"),
    ("naomi-raine-", "naomi-raine"),
    ("dante-bowe-", "dante-bowe"),
    ("chandler-moore-", "chandler-moore"),
    ("cody-carnes-", "cody-carnes"),
    ("kristian-stanfill-", "kristian-stanfill"),
    ("townend-", "stuart-townend"),
    ("stuart-townend-", "stuart-townend"),
    ("keith-and-kristyn-getty-", "keith-getty"),
    ("matt-boswell-", "matt-boswell"),
    ("shane-and-shane-", "shane-and-shane"),
    ("rita-springer-", "rita-springer"),
    ("vertical-worship-", "vertical-worship"),
    ("vertical-yes-i-will-", "vertical-worship"),
    ("hezekiah-walker-", "hezekiah-walker"),
    ("tye-tribbett-", "tye-tribbett"),
    ("anthony-brown-", "anthony-brown"),
    ("william-mcdowell-", "william-mcdowell"),
    ("william-murphy-", "william-murphy"),
    ("yolanda-adams-", "yolanda-adams"),
    ("brooklyn-tab-", "brooklyn-tabernacle"),
    ("marvin-sapp-", "marvin-sapp"),
    ("nathaniel-bassey-", "nathaniel-bassey"),
    ("mercy-chinwo-", "mercy-chinwo"),
    ("donnie-mcclurkin-", "donnie-mcclurkin"),
    ("fred-hammond-", "fred-hammond"),
    ("kirk-franklin-", "kirk-franklin"),
    ("plumb-", "plumb"),
    ("britt-nicole-", "britt-nicole"),
    ("ryan-stevenson-", "ryan-stevenson"),
    ("stars-go-dim-", "stars-go-dim"),
    ("audio-adrenaline-", "audio-adrenaline"),
    ("steven-curtis-chapman-", "steven-curtis-chapman"),
    ("sidewalk-prophets-", "sidewalk-prophets"),
    ("building-429-", "building-429"),
    ("big-daddy-weave-", "big-daddy-weave"),
    ("tenth-avenue-north-", "tenth-avenue-north"),
    ("aaron-shust-", "aaron-shust"),
    ("jeremy-camp-", "jeremy-camp"),
    ("jordan-smith-", "jordan-smith"),
    ("andrew-peterson-", "andrew-peterson"),
    ("river-valley-worship-", "river-valley-worship"),
    ("sohyang-", "sohyang"),
    ("park-jongho-", "park-jongho"),
    ("song-jungmi-", "song-jungmi"),
    ("park-soohyeon-", "park-soohyeon"),
    ("kim-yuria-", "kim-yuria"),
    ("kim-myungsik-", "kim-myungsik"),
    ("kim-jaejin-", "kim-jaejin"),
    ("kim-dohoon-", "kim-dohoon"),
    ("kim-minseo-", "kim-minseo"),
    ("kim-jiyeon-", "kim-jiyeon"),
    ("kim-junyoung-", "kim-junyoung"),
    ("kim-bokyu-", "kim-bokyu"),
    ("kim-giyoung-", "kim-giyoung"),
    ("han-woongjae-", "han-woongjae"),
    ("han-jinhee-", "han-jinhee"),
    ("hong-isaac-", "hong-isaac"),
    ("cheon-gwanwoong-", "cheon-gwanwoong"),
    ("kang-chan-", "kang-chan"),
    ("kang-myeongsik-", "kang-myeongsik"),
    ("kang-", "kang-myeongsik"),
    ("so-jinyoung-", "so-jinyoung"),
    ("onggi-", "onggi-jangi"),
    ("park-jeonggwan-", "park-jeonggwan"),
    ("jung-jongwon-", "jung-jongwon"),
    ("jung-hyunjin-", "jung-hyunjin"),
    ("majiha-", "maji-ha"),
    ("lim-hoseop-", "lim-hoseop"),
    ("shin-sangwoo-", "shin-sangwoo"),
    ("lee-cheonseok-", "lee-cheonseok"),
    ("park-jiyoung-", "park-jiyoung-worship"),
    ("heritage-mass-worship-", "heritage-mass-worship"),
    ("go-hyeongwon-", "go-hyeongwon-buheung"),
    ("nobuyoung-", "nobuyoung"),
    ("no-bua-", "nobuyoung"),
    ("praise-", "ko-anonymous-praise"),
    ("ost-", "ost"),
    ("classical-", "classical"),
    ("jazz-", "jazz-standard"),
    ("kpop-", "k-pop"),
    ("pop-", "pop"),
    # Round-3 prefixes (alt slug spellings)
    ("teamluke-", "team-luke-worship"),
    ("citipointe-", "citipointe-worship"),
    ("northpoint-", "northpoint-insideout"),
    ("gateway-", "gateway-worship"),
    ("feucht-", "sean-feucht"),
    ("sound-of-revival-", "sound-of-revival"),
    ("heritage-mass-", "heritage-mass-worship"),
    ("davidjonathan-", "davidjonathan-kim"),
    # Pop / jazz / standard ID suffixes for unknown one-offs
    ("memories-maroon-", "maroon-5"),
    ("as-it-was-", "harry-styles"),
    ("stay-justin-", "justin-bieber"),
    ("over-the-rainbow", "standard"),
    ("autumn-leaves-", "jazz-standard"),
    ("fly-me-to-the-moon", "jazz-standard"),
    # Korean-romanized prefix bucket — most of these come from older seed
    # rounds where the entry id was romanized rather than slug-team prefixed.
    # All belong to "한국 워시 (anonymous)" group.
    ("juman-barabolji-", "ko-anonymous-praise"),
    ("yeogi-kkaji-", "ko-anonymous-praise"),
    ("salahgyesinju", "ko-anonymous-praise"),
    ("yakhalttae-", "ko-anonymous-praise"),
    ("ju-an-e-", "ko-anonymous-praise"),
    ("ju-kke-", "ko-anonymous-praise"),
    ("ju-reul-", "ko-anonymous-praise"),
    ("ship-ja-ga-", "ko-anonymous-praise"),
    ("ju-nim-", "ko-anonymous-praise"),
    ("na-eui-", "ko-anonymous-praise"),
    ("ju-na-eui-", "ko-anonymous-praise"),
    ("yesu-na-ui-", "ko-anonymous-praise"),
    ("kim-sungji-", "ko-anonymous-praise"),
    ("worthy-of-it-all", "david-brymer"),
    ("isaiah6tyone-", "isaiah6tyone"),
    ("bridge-worship-oryun-", "bridge-worship-oryun"),
    ("presence-worship-oryun-", "presence-worship-oryun"),
    ("good-seeds-", "good-seeds"),
    ("fia-worship-", "fia-worship"),
]


# Explicit lineage patches for known Korean-translation / cover entries.
# Hand-curated because automatic title matching across languages is unreliable.
# Keys are song record ids; values are the original (canonical) song id.
LINEAGE_PATCHES: dict[str, str] = {
    # Way Maker family
    "anointing-way-maker": "way-maker",
    "yeram-way-maker": "way-maker",
    "agapao-way-maker": "way-maker",
    "markers-way-maker": "way-maker",
    "welove-way-maker-cover": "way-maker",
    "sinach-way-maker-live": "way-maker",
    # Reckless Love family
    "markers-reckless-love": "reckless-love",
    "welove-reckless-love-cover": "reckless-love",
    # Build My Life family
    "welove-build-my-life": "build-my-life",
    "passion-build-my-life-alt": "build-my-life",
    # Goodness of God family
    "markers-goodness-of-god": "goodness-of-god",
    "anointing-goodness-of-god": "goodness-of-god",
    # 10000 Reasons family
    "ywam-10000-reasons": "10000-reasons-bless-the-lord",
    "matt-redman-10000-reasons": "10000-reasons-bless-the-lord",
    # Oceans family
    "agapao-oceans": "oceans-where-feet-may-fail",
    "markers-oceans": "oceans-where-feet-may-fail",
    "hillsong-united-oceans": "oceans-where-feet-may-fail",
    # How Great Is Our God family
    "markers-how-great-is-our-god": "how-great-is-our-god",
    # What a Beautiful Name family
    "anointing-what-a-beautiful-name": "what-a-beautiful-name",
    # Cornerstone family
    "hillsong-cornerstone-young-free": "cornerstone",
    # King of Kings family
    "hillsong-king-of-kings-original": "king-of-kings",
    # Holy Forever family
    "brandon-lake-holy-forever-collab": "holy-forever",
    # Same God family (Elevation original)
    "maverick-brandon-lake-same-old-god": "same-god",
    # Yet Not I But Through Christ in Me family (root: cityalight-yet-not-i)
    "shane-and-shane-yet-not-i": "cityalight-yet-not-i",
    # Surrounded family
    "michael-w-smith-surrounded": "surrounded-fight-my-battles",
    # Praise (Elevation) family — root id is "praise-elevation"
    "elevation-jireh-praise-collab": "praise-elevation",
    # GIFTED family
    "sum-worship-living-as-children-arr": "gifted-living-as-children",
    "levistance-lamp-room": "gifted-living-as-children",
    # Holy Spirit (Torwalt) family
    "torwalt-holy-spirit": "holy-spirit-bryan-katie",
    # JESUSROAD Rock of Ages — hymn arrangement; flagged as such via tags but
    # we don't auto-link to a hymn record (different ID namespace).
    # Various Bethel cross-references
    "kim-walker-smith-hallelujah": "brian-doerksen-hallelujah",
    "kim-walker-smith-king-of-my-heart": "john-mark-mcmillan-king-of-my-heart",
    # Holy Forever (Tomlin original; Brandon Lake collab is a re-release)
    "brandon-lake-holy-forever-collab": "tomlin-holy-forever",
    # King of Kings — Hillsong original
    "hillsong-king-of-kings-original": "king-of-kings-hillsong",
    # Same God family — Brandon Lake version is an alt arrangement
    "maverick-brandon-lake-same-old-god": "same-god",
    # Defender — Rita Springer version IS the original (no separate root)
    # leave rita-springer-defender as `original`, not arrangement
}


# Fallback: artist-string substring → team slug. Used when id-prefix didn't
# match (e.g. id is the song slug rather than artist-prefix). Checked in
# order — first match wins.
ARTIST_SUBSTR_MAP: list[tuple[str, str]] = [
    ("Hillsong United", "hillsong-united"),
    ("Hillsong UNITED", "hillsong-united"),
    ("Hillsong Young", "hillsong-young-free"),
    ("Hillsong Y&F", "hillsong-young-free"),
    ("Hillsong Worship", "hillsong"),
    ("Hillsong", "hillsong"),
    ("Elevation Worship", "elevation"),
    ("Elevation", "elevation"),
    ("Bethel Music", "bethel"),
    ("Bethel", "bethel"),
    ("Maverick City", "maverick-city"),
    ("Passion", "passion"),
    ("Jesus Culture", "jesus-culture"),
    ("Vineyard", "vineyard"),
    ("Vertical Worship", "vertical-worship"),
    ("Mosaic MSC", "mosaic-msc"),
    ("CityAlight", "city-alight"),
    ("Sovereign Grace", "sovereign-grace"),
    ("We The Kingdom", "we-the-kingdom"),
    ("We the Kingdom", "we-the-kingdom"),
    ("IHOPKC", "ihopkc"),
    ("UPPERROOM", "upperroom"),
    ("Chris Tomlin", "chris-tomlin"),
    ("Phil Wickham", "phil-wickham"),
    ("Matt Redman", "matt-redman"),
    ("Matt Maher", "matt-maher"),
    ("Kari Jobe", "kari-jobe"),
    ("Brandon Lake", "brandon-lake"),
    ("Cody Carnes", "cody-carnes"),
    ("Chandler Moore", "chandler-moore"),
    ("Naomi Raine", "naomi-raine"),
    ("Dante Bowe", "dante-bowe"),
    ("Cory Asbury", "cory-asbury"),
    ("Brian Johnson", "brian-johnson"),
    ("Steffany Gretzinger", "steffany-gretzinger"),
    ("Kim Walker", "kim-walker-smith"),
    ("Bryan & Katie Torwalt", "torwalt"),
    ("Bryan Torwalt", "torwalt"),
    ("Crowder", "crowder"),
    ("David Crowder Band", "david-crowder-band"),
    ("Sinach", "sinach"),
    ("Tauren Wells", "tauren-wells"),
    ("Lauren Daigle", "lauren-daigle"),
    ("Casting Crowns", "casting-crowns"),
    ("MercyMe", "mercyme"),
    ("Newsboys", "newsboys"),
    ("for KING", "for-king-and-country"),
    ("Hillsong (", "hillsong"),
    ("Stuart Townend", "stuart-townend"),
    ("Keith & Kristyn Getty", "keith-getty"),
    ("Keith Getty", "keith-getty"),
    ("Matt Boswell", "matt-boswell"),
    ("Shane & Shane", "shane-and-shane"),
    ("Rita Springer", "rita-springer"),
    ("Travis Greene", "travis-greene"),
    ("Tasha Cobbs", "tasha-cobbs"),
    ("Israel Houghton", "israel-houghton"),
    ("Brooke Ligertwood", "brooke-ligertwood"),
    ("All Sons & Daughters", "all-sons-and-daughters"),
    ("Skillet", "skillet"),
    ("Lecrae", "lecrae"),
    ("TobyMac", "tobymac"),
    ("Sanctus Real", "sanctus-real"),
    ("Third Day", "third-day"),
    ("Michael W. Smith", "michael-w-smith"),
    ("Amy Grant", "amy-grant"),
    ("Rich Mullins", "rich-mullins"),
    ("Keith Green", "keith-green"),
    ("Aaron Shust", "aaron-shust"),
    ("Mandisa", "mandisa"),
    ("NEEDTOBREATHE", "needtobreathe"),
    ("Switchfoot", "switchfoot"),
    ("Relient K", "relient-k"),
    ("NF", "nf"),
    ("Forrest Frank", "forrest-frank"),
    ("Andy Mineo", "andy-mineo"),
    ("Anne Wilson", "anne-wilson"),
    ("Katy Nichole", "katy-nichole"),
    ("Hannah Kerr", "hannah-kerr"),
    ("Riley Clemmons", "riley-clemmons"),
    ("Selah", "selah"),
    ("Mark Schultz", "mark-schultz"),
    ("Mack Brock", "mack-brock"),
    ("Charity Gayle", "charity-gayle"),
    ("Misty Edwards", "misty-edwards"),
    ("Sean Curran", "sean-curran"),
    ("Pat Barrett", "pat-barrett"),
    ("Brian Doerksen", "brian-doerksen"),
    ("Brenton Brown", "brenton-brown"),
    ("Paul Baloche", "paul-baloche"),
    ("Tim Hughes", "tim-hughes"),
    ("Robin Mark", "robin-mark"),
    ("Delirious", "delirious"),
    ("Darrell Evans", "darrell-evans"),
    ("Don Moen", "don-moen"),
    ("Ron Kenoly", "ron-kenoly"),
    ("Lincoln Brewster", "lincoln-brewster"),
    ("John Mark McMillan", "john-mark-mcmillan"),
    ("Jeremy Camp", "jeremy-camp"),
    ("Kirk Franklin", "kirk-franklin"),
    ("Mercy Chinwo", "mercy-chinwo"),
    ("Nathaniel Bassey", "nathaniel-bassey"),
    ("Donnie McClurkin", "donnie-mcclurkin"),
    ("Fred Hammond", "fred-hammond"),
    ("Hezekiah Walker", "hezekiah-walker"),
    ("Tye Tribbett", "tye-tribbett"),
    ("Anthony Brown", "anthony-brown"),
    ("William McDowell", "william-mcdowell"),
    ("William Murphy", "william-murphy"),
    ("Yolanda Adams", "yolanda-adams"),
    ("Brooklyn Tabernacle", "brooklyn-tabernacle"),
    ("Marvin Sapp", "marvin-sapp"),
    ("DOE", "doe"),
    ("CAIN", "cain"),
    ("Zach Williams", "zach-williams"),
    ("Jordan Feliz", "jordan-feliz"),
    ("Andrew Peterson", "andrew-peterson"),
    ("Jordan Smith", "jordan-smith"),
    ("Plumb", "plumb"),
    ("Britt Nicole", "britt-nicole"),
    ("Ryan Stevenson", "ryan-stevenson"),
    ("Stars Go Dim", "stars-go-dim"),
    ("Audio Adrenaline", "audio-adrenaline"),
    ("Steven Curtis Chapman", "steven-curtis-chapman"),
    ("Sidewalk Prophets", "sidewalk-prophets"),
    ("Building 429", "building-429"),
    ("Big Daddy Weave", "big-daddy-weave"),
    ("Tenth Avenue North", "tenth-avenue-north"),
    ("Newsong Ministry", "newsong-ministry"),
    ("Aaron Shust", "aaron-shust"),
    ("마커스 워시", "markers"),
    ("마커스 워십", "markers"),
    ("마커스 미니스트리", "markers-ministry"),
    ("어노인팅", "anointing"),
    ("위러브", "welove"),
    ("WELOVE", "welove"),
    ("제이어스", "jus"),
    ("J-US", "jus"),
    ("예람워십", "yeram"),
    ("예람 워시", "yeram"),
    ("예수전도단", "ywam"),
    ("GIFTED", "gifted"),
    ("기프티드", "gifted"),
    ("JESUSROAD", "jesusroad"),
    ("예수로", "jesusroad"),
    ("SUM WORSHIP", "sum-worship"),
    ("성락교회", "sungrak-church"),
    ("달빛마을", "dalbit-maeul"),
    ("김복유", "kim-bokyu"),
    ("강명식", "kang-myeongsik"),
    ("강찬", "kang-chan"),
    ("한웅재", "han-woongjae"),
    ("홍이삭", "hong-isaac"),
    ("천관웅", "cheon-gwanwoong"),
    ("소진영", "so-jinyoung"),
    ("옹기장이", "onggi-jangi"),
    ("박종호", "park-jongho"),
    ("송정미", "song-jungmi"),
    ("소향", "sohyang"),
    ("김도훈", "kim-dohoon"),
    ("BTS", "k-pop-bts"),
    ("NewJeans", "k-pop-newjeans"),
    ("IU", "k-pop-iu"),
    ("BLACKPINK", "k-pop-blackpink"),
    ("AKMU", "k-pop-akmu"),
    ("aespa", "k-pop-aespa"),
    ("IVE", "k-pop-ive"),
    ("LE SSERAFIM", "k-pop-le-sserafim"),
    ("Coldplay", "coldplay"),
    ("Adele", "adele"),
    ("Ed Sheeran", "ed-sheeran"),
    ("Bruno Mars", "bruno-mars"),
    ("Frank Sinatra", "frank-sinatra"),
    ("Idina Menzel", "idina-menzel"),
    ("Pachelbel", "classical"),
    ("아이자야씩스티원", "isaiah6tyone"),
    ("Isaiah6tyOne", "isaiah6tyone"),
    ("Isaiah 6tyOne", "isaiah6tyone"),
    ("Isaiah 6tyone", "isaiah6tyone"),
]


def normalize_tags(tags: list[str], rec_id: str, year: int | None,
                   title: str, artist: str = "") -> list[str]:
    """Return a deduped/normalized tag list. Adds:
       - performed-by:{slug}  from id prefix
       - lineage from LINEAGE_PATCHES when known
       - live-version if title says 'Live' explicitly
       - release-type:youtube-only if 'youtube-only' or 'no-commercial-release' in old tags
    Does not remove existing tags.
    """
    out = list(tags)

    # Drop legacy duplicates we know are equivalent.
    legacy_replacements = {
        "no-commercial-release": "release-type:youtube-only",
        "youtube-only": "release-type:youtube-only",
        "instagram-only": "release-type:instagram-only",
        "self-composed": None,  # superseded by the `original` tag — manual flag, leave alone
        "self-composed-only": None,
    }
    for old, new in legacy_replacements.items():
        if old in out and new and new not in out:
            out.append(new)

    # performed-by from id prefix
    has_performed_by = any(t.startswith("performed-by:") for t in out)
    if not has_performed_by:
        for prefix, slug in PREFIX_TEAM_MAP:
            if rec_id.startswith(prefix):
                tag = f"performed-by:{slug}"
                if tag not in out:
                    out.append(tag)
                    has_performed_by = True
                break

    # Fallback: artist substring → team slug (for English-titled originals
    # whose ID is the song slug rather than an artist prefix).
    if not has_performed_by and artist:
        for pattern, slug in ARTIST_SUBSTR_MAP:
            if pattern in artist:
                tag = f"performed-by:{slug}"
                if tag not in out:
                    out.append(tag)
                break

    # Recent-year heuristic: 2024+ entries without release-type get
    # `release-type:single` (most recent worship releases drop as singles
    # rather than full albums). Doesn't override existing release-type.
    if year and year >= 2024:
        has_release_type = any(t.startswith("release-type:") for t in out)
        if not has_release_type:
            out.append("release-type:single")

    # lineage patches — authoritative. Strip any existing lineage tags for
    # this id and replace with the patch target.
    if rec_id in LINEAGE_PATCHES:
        original_id = LINEAGE_PATCHES[rec_id]
        out = [t for t in out
               if not t.startswith(("arrangement-of:", "cover-of:", "translation-of:"))]
        # Heuristic for which lineage flavor to use:
        #   - translation-of: Korean record (id contains -korean tokens or
        #     primary_language=="ko" — we approximate via id keywords).
        #   - arrangement-of: otherwise (English/instrumental rework).
        ko_markers = ("kor", "ko-", "ko_", "markers", "anointing", "welove",
                      "jus", "yeram", "ywam", "gifted", "jesusroad",
                      "sum-worship", "dalbit", "kim-", "kang-", "han-",
                      "park-", "song-", "lee-", "shin-", "choi-")
        is_ko_record = any(m in rec_id for m in ko_markers)
        prefix = "translation-of:" if is_ko_record else "arrangement-of:"
        out.append(f"{prefix}{original_id}")

    # live-version when title says so
    if "live-version" not in out and "studio-version" not in out:
        if re.search(r"\b[Ll]ive\b", title):
            out.append("live-version")

    # Dedupe while preserving order.
    seen = set()
    result = []
    for t in out:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def main() -> None:
    raw = SEED.read_text(encoding="utf-8")
    data = json.loads(raw)
    changes = 0
    for song in data.get("songs", []):
        sid = song.get("id", "")
        year = song.get("year")
        title = song.get("primary_title", "") or ""
        artist = song.get("artist", "") or ""
        before = list(song.get("tags") or [])
        after = normalize_tags(before, sid, year, title, artist=artist)
        if after != before:
            song["tags"] = after
            changes += 1

    # Custom JSON dump that keeps each song on a single line so diffs stay
    # readable. Use a placeholder approach: serialize the whole doc but
    # then collapse each song dict back to one line.
    pretty = json.dumps(data, ensure_ascii=False, indent=2)

    # Compact each song entry (which spans multiple lines after pretty-print)
    # back to a single line. We rely on the fact that song dicts inside the
    # "songs" array each start with `    {` (4-space indent) — they're the
    # only nested objects in that array.
    out_lines: list[str] = []
    buf: list[str] = []
    in_song = False
    depth_in_song = 0
    for line in pretty.split("\n"):
        if not in_song:
            # Heuristic: a song record opens on a line that is exactly the
            # 4-space-indent `{` after we've already entered the `"songs": [`
            # array. We track that by membership-counting `{` and `}` for
            # depth, but simpler: just detect lines matching `    {` and
            # `    {` start.
            if line == "    {":
                in_song = True
                buf = [line]
                depth_in_song = 1
                continue
            out_lines.append(line)
        else:
            buf.append(line.lstrip())
            # depth tracking — count braces in this line
            for ch in line:
                if ch == "{":
                    depth_in_song += 1
                elif ch == "}":
                    depth_in_song -= 1
            if depth_in_song == 0:
                # End of this song record. Re-emit on one line.
                # First buf line is "    {". Following lines need to become
                # a single space-separated key:value sequence.
                # We can just re-serialize the dict from raw — but we already
                # joined newlines/whitespace. Use json.loads on the joined
                # buffer to be safe.
                joined = "\n".join(buf)
                # Strip the trailing comma if present so json.loads works.
                trailing_comma = joined.rstrip().endswith(",")
                if trailing_comma:
                    obj_text = joined.rstrip().rstrip(",")
                else:
                    obj_text = joined
                obj = json.loads(obj_text)
                compact = json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
                out_lines.append("    " + compact + ("," if trailing_comma else ""))
                in_song = False
                buf = []

    SEED.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Retrofit complete: {changes} song(s) updated, {len(data['songs'])} total.")


if __name__ == "__main__":
    main()
