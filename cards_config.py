# ==================== КОНФИГУРАЦИЯ ВСЕГО ОБОРУДОВАНИЯ ====================

# Видеокарты (GPU)
GPU_CARDS = {
    # NVIDIA Серия GTX 10
    "gtx_1050_ti": {
        "name": "GTX 1050 Ti",
        "hash_rate": 15,
        "price": 500,
        "stock": 10,
        "description": "Отличная бюджетная карта для начала майнинга",
        "power": 75,
        "memory": 4,
        "release_year": 2016
    },
    "gtx_1060": {
        "name": "GTX 1060 6GB",
        "hash_rate": 22,
        "price": 800,
        "stock": 8,
        "description": "Легендарная карта, популярная среди майнеров",
        "power": 120,
        "memory": 6,
        "release_year": 2016
    },
    "gtx_1070": {
        "name": "GTX 1070",
        "hash_rate": 30,
        "price": 1200,
        "stock": 6,
        "description": "Высокая производительность для своего времени",
        "power": 150,
        "memory": 8,
        "release_year": 2016
    },
    "gtx_1070_ti": {
        "name": "GTX 1070 Ti",
        "hash_rate": 32,
        "price": 1400,
        "stock": 5,
        "description": "Улучшенная версия GTX 1070",
        "power": 180,
        "memory": 8,
        "release_year": 2017
    },
    "gtx_1080": {
        "name": "GTX 1080",
        "hash_rate": 35,
        "price": 1600,
        "stock": 4,
        "description": "Флагман серии 10",
        "power": 180,
        "memory": 8,
        "release_year": 2016
    },
    "gtx_1080_ti": {
        "name": "GTX 1080 Ti",
        "hash_rate": 40,
        "price": 2000,
        "stock": 3,
        "description": "Топовая карта серии 10",
        "power": 250,
        "memory": 11,
        "release_year": 2017
    },
    
    # NVIDIA Серия RTX 20
    "rtx_2060": {
        "name": "RTX 2060",
        "hash_rate": 28,
        "price": 1500,
        "stock": 7,
        "description": "Первая RTX карта с поддержкой трассировки лучей",
        "power": 160,
        "memory": 6,
        "release_year": 2019
    },
    "rtx_2060_super": {
        "name": "RTX 2060 Super",
        "hash_rate": 32,
        "price": 1800,
        "stock": 5,
        "description": "Улучшенная версия RTX 2060",
        "power": 175,
        "memory": 8,
        "release_year": 2019
    },
    "rtx_2070": {
        "name": "RTX 2070",
        "hash_rate": 38,
        "price": 2200,
        "stock": 4,
        "description": "Мощная карта для игр и майнинга",
        "power": 185,
        "memory": 8,
        "release_year": 2018
    },
    "rtx_2070_super": {
        "name": "RTX 2070 Super",
        "hash_rate": 42,
        "price": 2600,
        "stock": 3,
        "description": "Отличная производительность",
        "power": 215,
        "memory": 8,
        "release_year": 2019
    },
    "rtx_2080": {
        "name": "RTX 2080",
        "hash_rate": 45,
        "price": 3000,
        "stock": 2,
        "description": "Флагманская карта",
        "power": 225,
        "memory": 8,
        "release_year": 2018
    },
    "rtx_2080_ti": {
        "name": "RTX 2080 Ti",
        "hash_rate": 52,
        "price": 4000,
        "stock": 1,
        "description": "Топ серии 20",
        "power": 260,
        "memory": 11,
        "release_year": 2018
    },
    
    # NVIDIA Серия RTX 30
    "rtx_3060": {
        "name": "RTX 3060",
        "hash_rate": 45,
        "price": 2800,
        "stock": 5,
        "description": "Современная карта с отличным соотношением цены и производительности",
        "power": 170,
        "memory": 12,
        "release_year": 2021
    },
    "rtx_3060_ti": {
        "name": "RTX 3060 Ti",
        "hash_rate": 55,
        "price": 3500,
        "stock": 4,
        "description": "Более мощная версия RTX 3060",
        "power": 200,
        "memory": 8,
        "release_year": 2020
    },
    "rtx_3070": {
        "name": "RTX 3070",
        "hash_rate": 60,
        "price": 4200,
        "stock": 3,
        "description": "Отличная карта для майнинга",
        "power": 220,
        "memory": 8,
        "release_year": 2020
    },
    "rtx_3070_ti": {
        "name": "RTX 3070 Ti",
        "hash_rate": 65,
        "price": 4800,
        "stock": 2,
        "description": "Улучшенная версия RTX 3070",
        "power": 290,
        "memory": 8,
        "release_year": 2021
    },
    "rtx_3080": {
        "name": "RTX 3080",
        "hash_rate": 75,
        "price": 5500,
        "stock": 2,
        "description": "Мощная карта для профессионального майнинга",
        "power": 320,
        "memory": 10,
        "release_year": 2020
    },
    "rtx_3080_ti": {
        "name": "RTX 3080 Ti",
        "hash_rate": 82,
        "price": 6500,
        "stock": 1,
        "description": "Почти флагманская карта",
        "power": 350,
        "memory": 12,
        "release_year": 2021
    },
    "rtx_3090": {
        "name": "RTX 3090",
        "hash_rate": 90,
        "price": 8000,
        "stock": 1,
        "description": "Флагман серии 30",
        "power": 350,
        "memory": 24,
        "release_year": 2020
    },
    
    # AMD Серия RX 500
    "rx_570": {
        "name": "RX 570 4GB",
        "hash_rate": 25,
        "price": 600,
        "stock": 8,
        "description": "Популярная карта от AMD",
        "power": 150,
        "memory": 4,
        "release_year": 2017
    },
    "rx_580": {
        "name": "RX 580 8GB",
        "hash_rate": 30,
        "price": 900,
        "stock": 6,
        "description": "Улучшенная версия RX 570",
        "power": 185,
        "memory": 8,
        "release_year": 2017
    },
    
    # AMD Серия RX 5000
    "rx_5500_xt": {
        "name": "RX 5500 XT",
        "hash_rate": 28,
        "price": 1100,
        "stock": 5,
        "description": "Бюджетная карта нового поколения",
        "power": 130,
        "memory": 8,
        "release_year": 2019
    },
    "rx_5600_xt": {
        "name": "RX 5600 XT",
        "hash_rate": 38,
        "price": 1600,
        "stock": 4,
        "description": "Отличная карта для майнинга",
        "power": 150,
        "memory": 6,
        "release_year": 2020
    },
    "rx_5700": {
        "name": "RX 5700",
        "hash_rate": 48,
        "price": 2200,
        "stock": 3,
        "description": "Мощная карта",
        "power": 180,
        "memory": 8,
        "release_year": 2019
    },
    "rx_5700_xt": {
        "name": "RX 5700 XT",
        "hash_rate": 52,
        "price": 2800,
        "stock": 2,
        "description": "Топ серии 5000",
        "power": 225,
        "memory": 8,
        "release_year": 2019
    },
    
    # AMD Серия RX 6000
    "rx_6600": {
        "name": "RX 6600",
        "hash_rate": 42,
        "price": 2400,
        "stock": 4,
        "description": "Современная бюджетная карта",
        "power": 132,
        "memory": 8,
        "release_year": 2021
    },
    "rx_6600_xt": {
        "name": "RX 6600 XT",
        "hash_rate": 48,
        "price": 3000,
        "stock": 3,
        "description": "Улучшенная версия RX 6600",
        "power": 160,
        "memory": 8,
        "release_year": 2021
    },
    "rx_6700_xt": {
        "name": "RX 6700 XT",
        "hash_rate": 58,
        "price": 3800,
        "stock": 2,
        "description": "Отличная карта для майнинга",
        "power": 230,
        "memory": 12,
        "release_year": 2021
    },
    "rx_6800": {
        "name": "RX 6800",
        "hash_rate": 68,
        "price": 4800,
        "stock": 2,
        "description": "Мощная карта",
        "power": 250,
        "memory": 16,
        "release_year": 2020
    },
    "rx_6800_xt": {
        "name": "RX 6800 XT",
        "hash_rate": 72,
        "price": 5800,
        "stock": 1,
        "description": "Очень мощная карта",
        "power": 300,
        "memory": 16,
        "release_year": 2020
    },
    "rx_6900_xt": {
        "name": "RX 6900 XT",
        "hash_rate": 80,
        "price": 7500,
        "stock": 1,
        "description": "Флагман AMD",
        "power": 300,
        "memory": 16,
        "release_year": 2020
    }
}

# Куллеры (Coolers)
COOLERS = {
    "deepcool_fc120": {
        "name": "DEEPCOOL FC120",
        "price": 500,
        "stock": 20,
        "cooling_power": 30,
        "noise_level": 20,
        "power_consumption": 5,
        "wear_reduction": 10,
        "description": "Базовый кулер для охлаждения видеокарт"
    },
    "delta_afc1512dg": {
        "name": "Delta AFC1512DG",
        "price": 1200,
        "stock": 15,
        "cooling_power": 45,
        "noise_level": 35,
        "power_consumption": 8,
        "wear_reduction": 20,
        "description": "Средний кулер с хорошим охлаждением"
    },
    "delta_qfr1212he": {
        "name": "Delta QFR1212HE",
        "price": 2500,
        "stock": 10,
        "cooling_power": 70,
        "noise_level": 45,
        "power_consumption": 12,
        "wear_reduction": 30,
        "description": "Мощный кулер для профессионального майнинга"
    }
}

# ASIC-майнеры
ASICS = {
    "antminer_s9": {
        "name": "Antminer S9",
        "hash_rate": 13.5,
        "price": 50000,
        "stock": 5,
        "power_consumption": 1350,
        "wear_rate": 2,
        "noise_level": 75,
        "description": "Классический ASIC для Bitcoin, надежный и проверенный"
    },
    "antminer_s19_pro": {
        "name": "Antminer S19 Pro",
        "hash_rate": 110,
        "price": 150000,
        "stock": 3,
        "power_consumption": 3250,
        "wear_rate": 3,
        "noise_level": 80,
        "description": "Мощный ASIC для профессионального майнинга"
    },
    "whatsminer_m30s": {
        "name": "Whatsminer M30S",
        "hash_rate": 86,
        "price": 120000,
        "stock": 4,
        "power_consumption": 3400,
        "wear_rate": 2,
        "noise_level": 78,
        "description": "Эффективный ASIC от MicroBT с хорошим соотношением цена/качество"
    }
}

# GPU-риги
GPU_RIGS = {
    "mini_rig": {
        "name": "Mini Rig",
        "price": 20000,
        "stock": 10,
        "gpu_slots": 3,
        "cooler_slots": 1,
        "description": "Компактный риг на 3 видеокарты и 1 кулер. Идеален для начала",
        "max_power": 1000,
        "size": "компактный"
    },
    "midi_rig": {
        "name": "Midi Rig",
        "price": 35000,
        "stock": 8,
        "gpu_slots": 6,
        "cooler_slots": 2,
        "description": "Средний риг на 6 видеокарт и 2 кулера. Оптимальный выбор",
        "max_power": 2000,
        "size": "средний"
    },
    "mega_rig": {
        "name": "Mega Rig",
        "price": 50000,
        "stock": 5,
        "gpu_slots": 9,
        "cooler_slots": 3,
        "description": "Мощный риг на 9 видеокарт и 3 кулера. Для профессионального майнинга",
        "max_power": 3000,
        "size": "большой"
    }
}

# Стартовый ASIC для новых игроков
STARTER_ASIC = {
    "name": "Starter ASIC Mini",
    "hash_rate": 5,
    "price": 0,
    "description": "Базовый ASIC для начала майнинга",
    "power_consumption": 100,
    "wear_rate": 1
}