/**
 * Federal Bank branches — representative set for DEMO mode.
 * Source: federal_bank_branches.csv (1,800+ branches, 29 states).
 * This module contains ~90 key branches: Kerala-first (SOUTH zone priority),
 * plus representative branches from Tamil Nadu, Karnataka, Maharashtra, AP.
 *
 * DEMO ONLY — not imported in production; gated by VITE_DEPLOYMENT_MODE === 'DEMO'.
 */

export const FEDERAL_BANK_BRANCHES = [

  // ── Aluva / Head Office ────────────────────────────────────────────────────
  { ifsc: 'FDRL0000001', name: 'Head Office (Bank Junction)', city: 'Aluva',      district: 'Ernakulam', state: 'Kerala', pin: '683101', phone: '+914842633832' },
  { ifsc: 'FDRL0000035', name: 'Head Office — HAS',           city: 'Aluva',      district: 'Ernakulam', state: 'Kerala', pin: '683101', phone: '+914842201603' },
  { ifsc: 'FDRL0001001', name: 'Aluva Bank Junction',         city: 'Aluva',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842625173' },
  { ifsc: 'FDRL0001132', name: 'Aluva RSS',                   city: 'Aluva',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842620092' },
  { ifsc: 'FDRL0001512', name: 'Thaikkattukara',              city: 'Aluva',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842622596' },

  // ── Ernakulam / Kochi ─────────────────────────────────────────────────────
  { ifsc: 'FDRL0001375', name: 'Ernakulam Marine Drive',      city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '682031', phone: '+914842385518' },
  { ifsc: 'FDRL0001004', name: 'Ernakulam North',             city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842396974' },
  { ifsc: 'FDRL0001153', name: 'Ernakulam South (MG Road)',   city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842378710' },
  { ifsc: 'FDRL0001283', name: 'Ernakulam Broadway',          city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842366450' },
  { ifsc: 'FDRL0001380', name: 'Ernakulam Palarivattom',      city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842338230' },
  { ifsc: 'FDRL0001316', name: 'Ernakulam Panampilly Nagar',  city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842312549' },
  { ifsc: 'FDRL0001238', name: 'Ernakulam MG Road South',     city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '682016', phone: '+918089351099' },
  { ifsc: 'FDRL0001608', name: 'Ernakulam Bye Pass',          city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842345059' },
  { ifsc: 'FDRL0001410', name: 'Ernakulam Vyttila',           city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842389309' },
  { ifsc: 'FDRL0001686', name: 'Ernakulam Kathrukadavu',      city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842205313' },
  { ifsc: 'FDRL0001184', name: 'Edappally',                   city: 'Kochi',      district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842335148' },
  { ifsc: 'FDRL0001469', name: 'Kakkanad Seaport-Airport Rd', city: 'Kakkanad',   district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842421940' },
  { ifsc: 'FDRL0001464', name: 'Infopark Kakkanad',           city: 'Kakkanad',   district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842415050' },
  { ifsc: 'FDRL0001321', name: 'Arakunnam',                   city: 'Arakunnam',  district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842747800' },
  { ifsc: 'FDRL0001007', name: 'Edvanakkad',                  city: 'Edavanakkad',district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842505327' },
  { ifsc: 'FDRL0001114', name: 'Panangad',                    city: 'Panangad',   district: 'Ernakulam', state: 'Kerala', pin: '682506', phone: '+914842700268' },
  { ifsc: 'FDRL0001726', name: 'Cherai',                      city: 'Cherai',     district: 'Ernakulam', state: 'Kerala', pin: '',       phone: '+914842481788' },

  // ── Thrissur ──────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001279', name: 'Irinjalakuda',                city: 'Irinjalakuda',district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914802825335' },
  { ifsc: 'FDRL0001719', name: 'Irinjalakuda Nada',           city: 'Irinjalakuda',district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914802832120' },
  { ifsc: 'FDRL0001005', name: 'Chalakudy',                   city: 'Chalakudy',  district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914802709707' },
  { ifsc: 'FDRL0001888', name: 'Guruvayoor',                  city: 'Guruvayoor', district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914872557779' },
  { ifsc: 'FDRL0001432', name: 'Chavakkad',                   city: 'Chavakkad',  district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914872503120' },
  { ifsc: 'FDRL0001601', name: 'Chelakkara',                  city: 'Chelakkara', district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914884254848' },
  { ifsc: 'FDRL0001699', name: 'Cheruthuruthy',               city: 'Cheruthuruthy',district:'Thrissur',  state: 'Kerala', pin: '',       phone: '+914884262255' },
  { ifsc: 'FDRL0001570', name: 'Cherpu',                      city: 'Cherpu',     district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914936206089' },
  { ifsc: 'FDRL0001704', name: 'Amballur',                    city: 'Amballur',   district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914802757331' },
  { ifsc: 'FDRL0001703', name: 'Annamanada',                  city: 'Annamanada', district: 'Thrissur',  state: 'Kerala', pin: '680741', phone: '+914802773737' },
  { ifsc: 'FDRL0001256', name: 'Chowallurpady',               city: 'Guruvayoor', district: 'Thrissur',  state: 'Kerala', pin: '',       phone: '+914872556310' },
  { ifsc: 'FDRL0001087', name: 'Kakkathuruthy',               city: 'Irinjalakuda',district: 'Thrissur',  state: 'Kerala', pin: '680122', phone: '+914802848729' },

  // ── Kozhikode (Calicut) ───────────────────────────────────────────────────
  { ifsc: 'FDRL0001110', name: 'Cheruvannoor (Feroke)',       city: 'Kozhikode',  district: 'Kozhikode', state: 'Kerala', pin: '',       phone: '+914952482504' },
  { ifsc: 'FDRL0001710', name: 'Atholi',                      city: 'Kozhikode',  district: 'Kozhikode', state: 'Kerala', pin: '',       phone: '+914962674981' },
  { ifsc: 'FDRL0001111', name: 'Beypore',                     city: 'Beypore',    district: 'Kozhikode', state: 'Kerala', pin: '',       phone: '+914952414227' },
  { ifsc: 'FDRL0001955', name: 'Balussery',                   city: 'Balussery',  district: 'Kozhikode', state: 'Kerala', pin: '',       phone: '+914962640058' },
  { ifsc: 'FDRL0001744', name: 'Engapuzha',                   city: 'Kozhikode',  district: 'Kozhikode', state: 'Kerala', pin: '',       phone: '+914952235350' },
  { ifsc: 'FDRL0001496', name: 'Kozhikode Main',              city: 'Kozhikode',  district: 'Kozhikode', state: 'Kerala', pin: '673001', phone: '+914952720301' },

  // ── Kottayam ──────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001037', name: 'Changanassery',               city: 'Changanassery',district:'Kottayam',  state: 'Kerala', pin: '',       phone: '+914812420463' },
  { ifsc: 'FDRL0001044', name: 'Ettumanoor',                  city: 'Ettumanoor', district: 'Kottayam',  state: 'Kerala', pin: '',       phone: '+914812535530' },
  { ifsc: 'FDRL0001067', name: 'Gandhinagar Kottayam',        city: 'Kottayam',   district: 'Kottayam',  state: 'Kerala', pin: '',       phone: '+914812591308' },
  { ifsc: 'FDRL0001299', name: 'Chingavanam',                 city: 'Chingavanam',district: 'Kottayam',  state: 'Kerala', pin: '',       phone: '+914812430433' },
  { ifsc: 'FDRL0001254', name: 'Kadaplamattom',               city: 'Kadaplamattom',district:'Kottayam',  state: 'Kerala', pin: '',       phone: '+914822251053' },
  { ifsc: 'FDRL0001144', name: 'Aruvithura',                  city: 'Aruvithura', district: 'Kottayam',  state: 'Kerala', pin: '',       phone: '+914822275306' },
  { ifsc: 'FDRL0001795', name: 'Kurisummoodu',                city: 'Kottayam',   district: 'Kottayam',  state: 'Kerala', pin: '',       phone: '+914812720300' },

  // ── Alappuzha ─────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001015', name: 'Alappuzha (Mullackal)',       city: 'Alappuzha',  district: 'Alappuzha', state: 'Kerala', pin: '',       phone: '+914772261732' },
  { ifsc: 'FDRL0001331', name: 'Alappuzha Convent Square',    city: 'Alappuzha',  district: 'Alappuzha', state: 'Kerala', pin: '',       phone: '+914772246636' },
  { ifsc: 'FDRL0001095', name: 'Cherthala',                   city: 'Cherthala',  district: 'Alappuzha', state: 'Kerala', pin: '',       phone: '+914782813039' },
  { ifsc: 'FDRL0001396', name: 'Haripad',                     city: 'Haripad',    district: 'Alappuzha', state: 'Kerala', pin: '',       phone: '+914792416614' },
  { ifsc: 'FDRL0001024', name: 'Chengannur',                  city: 'Chengannur', district: 'Alappuzha', state: 'Kerala', pin: '',       phone: '+914792451119' },
  { ifsc: 'FDRL0001148', name: 'Ambalapuzha',                 city: 'Ambalapuzha',district: 'Alappuzha', state: 'Kerala', pin: '',       phone: '+914772272082' },

  // ── Thiruvananthapuram ────────────────────────────────────────────────────
  { ifsc: 'FDRL0001401', name: 'Attingal',                    city: 'Attingal',   district: 'Thiruvananthapuram', state: 'Kerala', pin: '', phone: '+914702625760' },
  { ifsc: 'FDRL0001733', name: 'Balaramapuram',               city: 'Balaramapuram',district:'Thiruvananthapuram', state: 'Kerala', pin: '', phone: '+914712400727' },
  { ifsc: 'FDRL0001066', name: 'Chirayinkeezhu',              city: 'Chirayinkeezhu',district:'Thiruvananthapuram',state: 'Kerala', pin: '', phone: '+914702640263' },
  { ifsc: 'FDRL0001325', name: 'Chembur (Ottasekharamangalam)',city: 'Thiruvananthapuram',district:'Thiruvananthapuram',state:'Kerala',pin:'',phone:'+914712255249' },
  { ifsc: 'FDRL0001229', name: 'Amboori',                     city: 'Amboori',    district: 'Thiruvananthapuram', state: 'Kerala', pin: '', phone: '+914712245389' },

  // ── Palakkad ──────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001764', name: 'Alathur',                     city: 'Alathur',    district: 'Palakkad',  state: 'Kerala', pin: '',       phone: '+914922222210' },
  { ifsc: 'FDRL0001089', name: 'Kalladikode',                 city: 'Kalladikode',district: 'Palakkad',  state: 'Kerala', pin: '',       phone: '+914924246222' },
  { ifsc: 'FDRL0001147', name: 'Alanallur',                   city: 'Alanallur',  district: 'Palakkad',  state: 'Kerala', pin: '',       phone: '+914924263492' },
  { ifsc: 'FDRL0001646', name: 'Chittur',                     city: 'Chittur',    district: 'Palakkad',  state: 'Kerala', pin: '',       phone: '+914923222276' },

  // ── Kannur ────────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001784', name: 'Chakkarakkal',                city: 'Kannur',     district: 'Kannur',    state: 'Kerala', pin: '',       phone: '+914972855582' },
  { ifsc: 'FDRL0001160', name: 'Cherupuzha',                  city: 'Cherupuzha', district: 'Kannur',    state: 'Kerala', pin: '',       phone: '+914895242830' },
  { ifsc: 'FDRL0001116', name: 'Chemberi',                    city: 'Chemberi',   district: 'Kannur',    state: 'Kerala', pin: '',       phone: '+914602213633' },
  { ifsc: 'FDRL0001458', name: 'Iritty',                      city: 'Iritty',     district: 'Kannur',    state: 'Kerala', pin: '',       phone: '+914902492700' },
  { ifsc: 'FDRL0002526', name: 'Chalode',                     city: 'Chalode',    district: 'Kannur',    state: 'Kerala', pin: '670595', phone: '+918921692568' },

  // ── Kollam ────────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001032', name: 'Anchal',                      city: 'Anchal',     district: 'Kollam',    state: 'Kerala', pin: '',       phone: '+91472271149'  },
  { ifsc: 'FDRL0001278', name: 'Chathannoor',                 city: 'Chathannoor',district: 'Kollam',    state: 'Kerala', pin: '',       phone: '+914742593395' },
  { ifsc: 'FDRL0001143', name: 'Chavara',                     city: 'Chavara',    district: 'Kollam',    state: 'Kerala', pin: '',       phone: '+914762682833' },
  { ifsc: 'FDRL0001731', name: 'Ayur',                        city: 'Ayur',       district: 'Kollam',    state: 'Kerala', pin: '',       phone: '+914752293838' },

  // ── Idukki ────────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001091', name: 'Idukki Colony',               city: 'Idukki',     district: 'Idukki',    state: 'Kerala', pin: '',       phone: '+914862235334' },
  { ifsc: 'FDRL0001137', name: 'Erattayar',                   city: 'Erattayar',  district: 'Idukki',    state: 'Kerala', pin: '',       phone: '+914868276006' },
  { ifsc: 'FDRL0001844', name: 'Thodupuzha (Mangattukavala)', city: 'Thodupuzha', district: 'Idukki',    state: 'Kerala', pin: '685585', phone: '+914862220610' },

  // ── Malappuram ────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001128', name: 'Angadipuram',                 city: 'Angadipuram',district: 'Malappuram',state: 'Kerala', pin: '',       phone: '+91493226672'  },
  { ifsc: 'FDRL0001077', name: 'Areacode',                    city: 'Areacode',   district: 'Malappuram',state: 'Kerala', pin: '',       phone: '+914832850239' },
  { ifsc: 'FDRL0001547', name: 'Edappal',                     city: 'Edappal',    district: 'Malappuram',state: 'Kerala', pin: '',       phone: '+914942684481' },

  // ── Pathanamthitta ────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001208', name: 'Arattupuzha',                 city: 'Arattupuzha',district: 'Pathanamthitta',state:'Kerala',pin:'',      phone: '+914682317487' },
  { ifsc: 'FDRL0001201', name: 'Chandanappally',              city: 'Chandanappally',district:'Pathanamthitta',state:'Kerala',pin:'',    phone: '+914682351296' },
  { ifsc: 'FDRL0001085', name: 'Elanthoor',                   city: 'Elanthoor',  district: 'Pathanamthitta',state:'Kerala',pin:'',      phone: '+914682361050' },
  { ifsc: 'FDRL0001134', name: 'Eraviperoor',                 city: 'Eraviperoor',district: 'Pathanamthitta',state:'Kerala',pin:'',      phone: '+914692666203' },

  // ── Tamil Nadu ────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001683', name: 'Tirupati',                    city: 'Tirupati',   district: 'Tirupati',  state: 'Andhra Pradesh', pin: '517501', phone: '+918772231361' },
  { ifsc: 'FDRL0001626', name: 'Kakinada',                    city: 'Kakinada',   district: 'Kakinada',  state: 'Andhra Pradesh', pin: '',       phone: '+918688396767' },
  { ifsc: 'FDRL0001671', name: 'Guntur',                      city: 'Guntur',     district: 'Guntur',    state: 'Andhra Pradesh', pin: '',       phone: '+918632332277' },

  // ── Karnataka ─────────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001318', name: 'Bangalore Basavanagudi',      city: 'Bengaluru',  district: 'Bengaluru Urban', state: 'Karnataka', pin: '', phone: '+918026565323' },
  { ifsc: 'FDRL0001535', name: 'Bangalore Indiranagar',       city: 'Bengaluru',  district: 'Bengaluru Urban', state: 'Karnataka', pin: '', phone: '+918025212341' },
  { ifsc: 'FDRL0001437', name: 'Bangalore Koramangala',       city: 'Bengaluru',  district: 'Bengaluru Urban', state: 'Karnataka', pin: '', phone: '+918025702162' },
  { ifsc: 'FDRL0001781', name: 'Bangalore Banashankari',      city: 'Bengaluru',  district: 'Bengaluru Urban', state: 'Karnataka', pin: '', phone: '+918023159123' },
  { ifsc: 'FDRL0002071', name: 'BC Road (Bantwal Cross)',      city: 'Mangaluru',  district: 'Dakshina Kannada',state: 'Karnataka', pin: '', phone: '+919945923176' },

  // ── Maharashtra ───────────────────────────────────────────────────────────
  { ifsc: 'FDRL0001105', name: 'New Delhi Connaught Circus',  city: 'New Delhi',  district: 'New Delhi', state: 'Delhi', pin: '',       phone: '+911149785701' },
  { ifsc: 'FDRL0001343', name: 'Surat',                       city: 'Surat',      district: 'Surat',     state: 'Gujarat', pin: '',      phone: '+9149362329364' },
  { ifsc: 'FDRL0001158', name: 'Ahmedabad (Ashram Road)',     city: 'Ahmedabad',  district: 'Ahmedabad', state: 'Gujarat', pin: '',      phone: '+917926588103' },

]

/** Returns branches filtered by state code (e.g., 'Kerala', 'Tamil Nadu') */
export function getBranchesByState(state) {
  return FEDERAL_BANK_BRANCHES.filter(b => b.state === state)
}

/** Returns branches filtered by district */
export function getBranchesByDistrict(district) {
  return FEDERAL_BANK_BRANCHES.filter(b => b.district === district)
}

/** Returns a branch by IFSC code */
export function getBranchByIfsc(ifsc) {
  return FEDERAL_BANK_BRANCHES.find(b => b.ifsc === ifsc) ?? null
}

export const BRANCH_COUNT = FEDERAL_BANK_BRANCHES.length
