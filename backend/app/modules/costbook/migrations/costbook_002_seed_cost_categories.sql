-- ============================================================
-- costbook_002_seed_cost_categories.sql
-- Seeds all cost categories from the master budget spreadsheet.
-- Safe to re-run (ON CONFLICT DO NOTHING).
-- ============================================================

BEGIN;

INSERT INTO costbook.cost_categories (po_number, section, description, formula_notes, sort_order) VALUES

-- Permits & Fees
('1010', 'Permits & Fees',               'Building Permits',                         'Price from Permit Tech — $3,500 standard',                                                           10),
('1020', 'Permits & Fees',               'New Home Warranty',                         'Price from Suzanne — $600',                                                                          20),
('1030', 'Permits & Fees',               'Construction Insurance',                    'Set Price $700',                                                                                     30),
('1040', 'Permits & Fees',               'Property Tax',                              'Set Price $800 new development (infill case by case)',                                               40),

-- Architectural & Engineering
('1110', 'Architectural & Engineering',  'Drafting',                                  'Set Price $1.50 per sqft',                                                                           50),
('1120', 'Architectural & Engineering',  'Engineer',                                  'JL Rocke $750 / DG Bell $500 / Winnipeg City $2,000',                                               60),
('1130', 'Architectural & Engineering',  'Surveys',                                   'B&D Pricing — Winnipeg/WSP/Headingly/Oakbank $790 / Dugald/Stonewall/Lorette/Niverville/Landmark $840 / Grande Pointe $1,545', 70),
('1140', 'Architectural & Engineering',  'Estimating/Budgeting',                      'Set Price $1,400',                                                                                   80),

-- Site Work
('1210', 'Site Work',                    'Fill Dirt and Material',                    'Set price $2,000 unless otherwise specified',                                                        90),
('1220', 'Site Work',                    'Toilet',                                    'Set Price $900 or zero for Ventura Developments',                                                   100),
('1230', 'Site Work',                    'Fence (site)',                              'Set Price $500 city only — zero for rural',                                                         110),
('1240', 'Site Work',                    'Garbage',                                   '$185 per empty + $185 extra for drywall. 1000–1200sqft=$1,480 / 1201–1600sqft=$1,665 / 1600+sqft=$1,850 / add $370 finished basement', 120),
('1250', 'Site Work',                    'Tree Removal/Stump Grinding',               'Case by case — $0 default',                                                                         130),

-- Demolition
('1310', 'Demolition',                   'Demolition',                                'Infill only — case by case',                                                                        140),
('1320', 'Demolition',                   'Asbestos Testing',                          'Infill only — case by case',                                                                        150),

-- Utility Connections
('1410', 'Utility Connections',          'Water and Sewer',                           '$2,950 gravity sewer by Precision OR quote by contractor',                                          160),
('1420', 'Utility Connections',          'Manitoba Hydro Bill',                       'Set price $1,500',                                                                                  170),
('1430', 'Utility Connections',          'Water Bill',                                'Set price $50',                                                                                     180),

-- Excavation
('2010', 'Excavation',                   'Excavation & Backfill',                     '$1,850 standard or $3,000 for basement wood floor',                                                 190),
('2020', 'Excavation',                   'Earth Hauling',                             'Set Price $2,000 unless otherwise specified',                                                        200),

-- Foundation & Concrete Slab
('2110', 'Foundation & Concrete Slab',   'Foundation Materials',                      'Price Sheet formula (WM Dyck Estimate) — use $4,500 for prelim budget',                            210),
('2120', 'Foundation & Concrete Slab',   'Concrete',                                  'Price sheet formula — $18/sqft prelim. Add winter charge Sept 1–Mar 31: $22/m³',                   220),
('2130', 'Foundation & Concrete Slab',   'Gravel/Sand (Piles, B Slab, G Slab)',       'Set price $5,200 with garage / $3,800 no garage',                                                   230),
('2140', 'Foundation & Concrete Slab',   'Rebar Package',                             'Quote + PST + delivery (Mid Canada) — $2,600 prelim budget',                                        240),
('2150', 'Foundation & Concrete Slab',   'Labor — Piles, Walls, Garage Beam',         'Price sheet formula',                                                                               250),
('2160', 'Foundation & Concrete Slab',   'Concrete Pump (Piles, Walls, B Slab)',      'Set price $750 per pump — 3 pumps standard (piles, foundation walls, basement slab)',              260),
('2170', 'Foundation & Concrete Slab',   'Pile Driller',                              '16"x20\'=$51/pile / 16"x25\'=$63.75/pile / remove house tailings $275/visit / garage tailings $110/visit', 270),
('2180', 'Foundation & Concrete Slab',   'Steel Beam and Craning',                    'Quote + PST + 3 hours craning — $3,500 prelim budget',                                             280),
('2190', 'Foundation & Concrete Slab',   'Labor B Slab — prep, place, finish, pipe',  'Set Price: basement sqft x $2.50 + $400',                                                           290),
('2200', 'Foundation & Concrete Slab',   'Labor G Slab — prep, place, finish',        'Set Price: sqft x $4.20 (labour & rebar included)',                                                 300),
('2210', 'Foundation & Concrete Slab',   'Labor Front Step (form, place, finish)',    'Price sheet for CIP or $2,500',                                                                     310),
('2220', 'Foundation & Concrete Slab',   'Rough Grade',                               'Set Price $3,300 unless otherwise specified',                                                        320),
('2230', 'Foundation & Concrete Slab',   'Foundation Extras',                         'Case by case',                                                                                      330),

-- Framing
('3110', 'Framing',                      'Framing Materials',                         'Quote (Material list) — $22/sqft prelim budget',                                                    340),
('3120', 'Framing',                      'Materials — Trusses',                       'Quote + PST',                                                                                       350),
('3121', 'Framing',                      'Craning — Trusses',                         '$792 for crane — double crane for 2 storey',                                                        360),
('3130', 'Framing',                      'Framing Labor',                             '$9/sqft main floor (+ second floor if required) plus frost walls $1,000',                          370),
('3140', 'Framing',                      'Stairs — Manufacture and Deliver',          'Quote or $1,500',                                                                                   380),
('3150', 'Framing',                      'Roofing Labor',                             'Material list bundles + starter strip + ridge cap x $20 + 10% waste',                              390),
('3160', 'Framing',                      'Framing Extras',                            'Case by case — add finished basement framing labor $1,500 here',                                   400),

-- Plumbing
('3210', 'Plumbing',                     'Plumbing',                                  'Quote or $6,800 (2 bath bungalow) labor + HWT + heat recovery / $6,200 (2 bath 2 storey)',         410),

-- Electrical
('3310', 'Electrical',                   'Electrical',                                'Electrical quote',                                                                                  420),
('3320', 'Electrical',                   'Data',                                      'Data quote',                                                                                        430),
('3330', 'Electrical',                   'Central Vac',                               'Central vac if needed (check selection sheet)',                                                     440),
('3340', 'Electrical',                   'Client Extras / Heaters',                   '$428 in winter for heaters unless accounted for in PO 3310',                                       450),

-- HVAC
('3810', 'HVAC',                         'HVAC',                                      'Quote or $8/sqft',                                                                                  460),
('3820', 'HVAC',                         'AC',                                        'Quote or $2,800 prelim budget',                                                                     470),

-- Windows
('4510', 'Windows',                      'Windows',                                   'Approved window order — include all prices',                                                        480),
('4520', 'Windows',                      'Window Extras',                             'Quote',                                                                                             490),
('4530', 'Windows',                      'Window Wells',                              '$266.20 per basement window requiring a window well',                                               500),

-- Garage Doors
('4610', 'Garage Doors',                 'Garage Doors/Openers (material & labor)',   'Quote',                                                                                             510),
('4620', 'Garage Doors',                 'Garage Door/Opener Extras',                 'Quote',                                                                                             520),

-- Exterior Finishing
('4805', 'Exterior Finishing',           'Metal Cladding',                            'Quote',                                                                                             530),
('4810', 'Exterior Finishing',           'Soffit, Fascia, Gutters, Downspout, Flashing', 'Quote',                                                                                         540),
('4820', 'Exterior Finishing',           'Conventional Stucco',                       'Quote',                                                                                             550),
('4830', 'Exterior Finishing',           'Acrylic Stucco',                            'Quote',                                                                                             560),
('4840', 'Exterior Finishing',           'Stone (supply & install)',                  'Quote',                                                                                             570),
('4850', 'Exterior Finishing',           'Window Trim',                               'Quote',                                                                                             580),
('4860', 'Exterior Finishing',           'Siding Labor',                              'Quote',                                                                                             590),
('4861', 'Exterior Finishing',           'Siding Material',                           'Quote',                                                                                             600),
('4870', 'Exterior Finishing',           'Front Step Railing',                        'Quote',                                                                                             610),

-- Insulation & Drywall
('5010', 'Insulation & Drywall',         'Supply & Install — insulation, poly, drywall, taping, attic blow-in', 'Quote or $16/sqft prelim budget',                                        620),
('5020', 'Insulation & Drywall',         'Spray Foam Joist',                          'Main floor rim joists $9/lnft + basement rim joists $9.75/lnft + cantilevers $17/lnft + fireproofing $4/lnft', 630),

-- Flooring
('5110', 'Flooring',                     'Base Flooring',                             'Quote or $5.50/sqft prelim budget',                                                                 640),
('5120', 'Flooring',                     'Extra Flooring',                            'Quote — budget = difference',                                                                       650),

-- Interior Finishing
('5210', 'Interior Finishing',           'Painting (supply & install)',               'Quote or $3.10/sqft prelim budget (always use Funks quote)',                                        660),
('5220', 'Interior Finishing',           'Interior finishing, hardware & exterior door hardware', 'Quote from Annette',                                                                    670),
('5230', 'Interior Finishing',           'Closet Shelving',                           'Quote from Classic Closets',                                                                        680),
('5240', 'Interior Finishing',           'Interior Trim & Door Labor',                'Price sheet formula',                                                                               690),
('5250', 'Interior Finishing',           'Mirrors Supply & Install',                  'Quote from Classic Closets',                                                                        700),
('5260', 'Interior Finishing',           'Shower Doors',                              'Quote',                                                                                             710),
('5270', 'Interior Finishing',           'Interior Railing',                          'Quote',                                                                                             720),
('5280', 'Interior Finishing',           'Tile Backsplash',                           'Quote',                                                                                             730),
('5290', 'Interior Finishing',           'Designer & Staging',                        '$0 unless otherwise specified',                                                                     740),
('5310', 'Interior Finishing',           'Fireplace',                                 'Quote',                                                                                             750),
('5320', 'Interior Finishing',           'Tile Shower',                               'Quote',                                                                                             760),

-- Cabinetry
('5402', 'Cabinetry',                    'Kitchen & Bath Cabinets',                   'Quote from Twilight or $7,000',                                                                     770),
('5404', 'Cabinetry',                    'Kitchen & Bath Counters',                   'Quote from Twilight or KCD',                                                                        780),
('5406', 'Cabinetry',                    'Kitchen & Bath Labor',                      '$30/cabinet, $40/laminate top piece',                                                               790),
('5408', 'Cabinetry',                    'Kitchen & Bath Extras',                     '$150 hood fan / $400 full package',                                                                 800),

-- Appliances
('5502', 'Appliances',                   'Appliance Installation',                    'Quote from PegCity ($160.50)',                                                                      810),
('5504', 'Appliances',                   'Kitchen & Laundry Appliances',              'Quote from Dufresne or Wiens + PST + $10 delivery',                                                820),
('5506', 'Appliances',                   'Kitchen & Laundry Appliance Extras',        'Quote',                                                                                             830),

-- Plumbing Fixtures
('5610', 'Plumbing Fixtures',            'Tub-Shower Order',                          'Quote or $2,000',                                                                                  840),
('5620', 'Plumbing Fixtures',            'Plumbing Fixtures',                         'Quote or $2,000',                                                                                  850),
('5621', 'Plumbing Fixtures',            'Plumbing Fixture Extras',                   'Quote',                                                                                             860),

-- Electrical Fixtures
('5710', 'Electrical Fixtures',          'Finish Electrical Fixtures',                'Quote or $1,500',                                                                                  870),
('5720', 'Electrical Fixtures',          'Finish Electrical Fixture Extras',          'Quote — $1,500 = difference',                                                                      880),

-- Building Clean-Up
('6010', 'Building Clean-Up',            'Final Grade',                               'Set price $4,000',                                                                                  890),
('6020', 'Building Clean-Up',            'Building Clean-up',                         '$0.52/sqft + $100 for unfinished basement. Add $0.15/sqft for spec house re-clean',                900),
('6030', 'Building Clean-Up',            'Duct Cleaning',                             '$347 + tax',                                                                                        910),

-- Landscaping
('6110', 'Landscaping',                  'Top Soil',                                  'Quote',                                                                                             920),
('6120', 'Landscaping',                  'Trees',                                     'Quote',                                                                                             930),
('6130', 'Landscaping',                  'Sod',                                       'Quote',                                                                                             940),
('6140', 'Landscaping',                  'Seed',                                      'Quote',                                                                                             950),
('6150', 'Landscaping',                  'Deck/Patio',                                'Quote',                                                                                             960),
('6160', 'Landscaping',                  'Fence',                                     'Quote',                                                                                             970),
('6180', 'Landscaping',                  'Driveway (materials, gravel & labor)',      'Gravel $3,500 / Concrete $7,500 / Grande Pointe $11,000 (refer to OTP Sale for job-specific)',      980),

-- Other
('6200', 'Other',                        'Contingency',                               'Subtotal x 2.5%',                                                                                   990),
('6330', 'Other',                        'Land',                                      'Actual land cost from OTP Land',                                                                   1000),
('6340', 'Other',                        'Land Holding Costs',                        'Set Price $2,500',                                                                                 1010),
('6350', 'Other',                        'Realtor',                                   'Sale price / 1.05 − land = net; net x commission rate',                                            1020),
('6360', 'Other',                        'Legal',                                     'Set Price $2,500',                                                                                 1030),
('6800', 'Other',                        'Warranty (materials & labor)',              'Set Price $2,500',                                                                                 1040),
('6850', 'Other',                        'Other',                                     'Case by case',                                                                                     1050)

ON CONFLICT (po_number) DO NOTHING;

COMMIT;
