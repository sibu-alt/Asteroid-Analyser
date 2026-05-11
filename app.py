from flask import Flask, render_template, request, jsonify
import requests
import json
from datetime import datetime, timedelta
import random
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = 'asteroid-mining-analyzer-secret-key'

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

NASA_API_KEY = 'CrX4F53URlS2xeLMoziHfI89l8KRwO51V0sMS4vD'  
NASA_BASE_URL = 'https://api.nasa.gov/neo/rest/v1/neo/'
JPL_SBDB_URL = 'https://ssd-api.jpl.nasa.gov/sbdb.api'

ASTEROID_TYPES = {
    'C-type': {
        'description': 'Carbonaceous chondrites - Rich in water, carbon, and silicates',
        'minerals': {
            'Water Ice': 0.20,
            'Nickel-Iron': 0.05,
            'Platinum Group': 0.001,
            'Silicate Minerals': 0.50,
            'Carbon Compounds': 0.20,
            'Rare Earth Elements': 0.005
        },
        'color': 'primary',
        'abundance': 0.75
    },
    'S-type': {
        'description': 'Stony/silicate asteroids - High in nickel-iron and silicates',
        'minerals': {
            'Nickel-Iron': 0.20,
            'Magnesium Silicates': 0.40,
            'Platinum Group': 0.01,
            'Gold': 0.001,
            'Copper': 0.05,
            'Silicon': 0.30
        },
        'color': 'success',
        'abundance': 0.17
    },
    'M-type': {
        'description': 'Metallic asteroids - Very high in metals and precious elements',
        'minerals': {
            'Nickel-Iron': 0.80,
            'Platinum Group': 0.05,
            'Gold': 0.01,
            'Cobalt': 0.03,
            'Iridium': 0.005,
            'Palladium': 0.01
        },
        'color': 'warning',
        'abundance': 0.08
    }
}


def get_rotation_period(asteroid_name_or_id):
    """
    Fetch rotation period from JPL Small Body Database API.
    
    Returns a dict:
      {
        'period_hours': float or None,
        'source': 'jpl' | 'unavailable',
        'raw': the raw string value from JPL, e.g. '4.296'
      }
    
    The SBDB phys_par field 'rot_per' gives the rotation period in hours.
    If the object is not found or the field is absent, returns None for period.
    """
    try:
        params = {
            'sstr': asteroid_name_or_id,
            'phys-par': 1  
        }
        
        logger.info(f'Fetching rotation period from JPL SBDB for: {asteroid_name_or_id}')
        response = requests.get(JPL_SBDB_URL, params=params, timeout=8)
        
        if response.status_code != 200:
            logger.warning(f'JPL SBDB returned {response.status_code} for {asteroid_name_or_id}')
            return {'period_hours': None, 'source': 'unavailable', 'raw': None}
        
        data = response.json()
        
        phys_par = data.get('phys_par', [])
        
        for param in phys_par:
            if param.get('name') == 'rot_per':
                raw_value = param.get('value')
                if raw_value is not None:
                    try:
                        period_hours = float(raw_value)
                        logger.info(f'Rotation period for {asteroid_name_or_id}: {period_hours} hours')
                        return {
                            'period_hours': period_hours,
                            'source': 'jpl',
                            'raw': raw_value
                        }
                    except (ValueError, TypeError):
                        logger.warning(f'Could not parse rotation period value: {raw_value}')
                        return {'period_hours': None, 'source': 'unavailable', 'raw': raw_value}
        
        logger.info(f'No rotation period found in JPL SBDB for {asteroid_name_or_id}')
        return {'period_hours': None, 'source': 'unavailable', 'raw': None}
    
    except requests.exceptions.Timeout:
        logger.warning(f'JPL SBDB timeout for {asteroid_name_or_id}')
        return {'period_hours': None, 'source': 'unavailable', 'raw': None}
    except Exception as e:
        logger.error(f'Error fetching rotation period: {str(e)}')
        return {'period_hours': None, 'source': 'unavailable', 'raw': None}


def rotation_period_to_score(period_hours):
    """
    Convert a rotation period (in hours) to a 0-100 mining suitability score.
    
    Mining preference:
      - Too fast (< 2h): surface material flies off, very hard to anchor — poor
      - Ideal range (2–24h): stable, workable surface — excellent
      - Slow (24–168h / 1 week): manageable but less efficient — good
      - Very slow (> 168h): long shadow/thermal cycles, complicates operations — moderate
    """
    if period_hours < 2.0:
        return 20   
    elif period_hours <= 6.0:
        return 75  
    elif period_hours <= 24.0:
        return 95  
    elif period_hours <= 72.0:
        return 80   
    elif period_hours <= 168.0:
        return 60   
    else:
        return 40  


def calculate_suitability_score(asteroid_data, rotation_info=None):
    """Calculate mining suitability score (0-100)"""
    
    close_approach = asteroid_data.get('close_approach_data', {})
    diameter_data = asteroid_data.get('estimated_diameter', {}).get('kilometers', {})
    distance_score = 50  
    if close_approach and 'miss_distance' in close_approach:
        miss_km = float(close_approach['miss_distance'].get('kilometers', 1e9))
        au_distance = miss_km / 149597870.7 
        
        if au_distance < 0.1:
            distance_score = 95
        elif au_distance < 0.5:
            distance_score = 80
        elif au_distance < 1.0:
            distance_score = 65
        elif au_distance < 2.5:
            distance_score = 50
        else:
            distance_score = 30
    
    size_score = 60  
    if diameter_data:
        avg_diameter = (
            diameter_data.get('estimated_diameter_min', 0) + 
            diameter_data.get('estimated_diameter_max', 0)
        ) / 2
        
        if 0.5 <= avg_diameter <= 2.0:
            size_score = 90
        elif avg_diameter < 0.1:
            size_score = 20
        elif avg_diameter > 10.0:
            size_score = 40
        else:
            size_score = 70
    
    composition_scores = {'M-type': 90, 'S-type': 75, 'C-type': 60}
    asteroid_type = determine_asteroid_type(asteroid_data)
    composition_score = composition_scores.get(asteroid_type, 50)
    
    if rotation_info and rotation_info.get('period_hours') is not None:
        rotation_score = rotation_period_to_score(rotation_info['period_hours'])
        rotation_data_source = 'jpl'
    else:
        rotation_score = random.randint(40, 90)
        rotation_data_source = 'simulated'

    total_score = (
        distance_score * 0.35 +
        size_score * 0.25 +
        composition_score * 0.30 +
        rotation_score * 0.10
    )
    
    return {
        'total': round(total_score, 2),
        'components': {
            'distance': round(distance_score, 2),
            'size': round(size_score, 2),
            'composition': round(composition_score, 2),
            'rotation': round(rotation_score, 2)
        },
        'rotation_data_source': rotation_data_source
    }

def determine_asteroid_type(asteroid_data):
    """Determine asteroid type based on available data"""
    orbital_data = asteroid_data.get('orbital_data', {})
    
    if orbital_data and 'semi_major_axis' in orbital_data:
        semi_major = float(orbital_data['semi_major_axis'])
        
        if semi_major < 2.0:
            return 'S-type'
        elif semi_major < 2.5:
            return random.choices(['M-type', 'S-type'], weights=[0.3, 0.7])[0]
        elif semi_major < 3.0:
            return random.choices(['C-type', 'S-type', 'M-type'], weights=[0.6, 0.3, 0.1])[0]
        else:
            return 'C-type'
    
    return random.choices(
        ['C-type', 'S-type', 'M-type'],
        weights=[0.75, 0.17, 0.08]
    )[0]

def get_suitability_category(score):
    """Categorize mining suitability"""
    if score >= 80:
        return {'name': 'Excellent', 'color': 'success', 'icon': 'fa-gem'}
    elif score >= 65:
        return {'name': 'Good', 'color': 'primary', 'icon': 'fa-thumbs-up'}
    elif score >= 50:
        return {'name': 'Moderate', 'color': 'warning', 'icon': 'fa-balance-scale'}
    elif score >= 35:
        return {'name': 'Marginal', 'color': 'orange', 'icon': 'fa-exclamation-triangle'}
    else:
        return {'name': 'Poor', 'color': 'danger', 'icon': 'fa-times-circle'}

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_asteroid():
    """Analyze asteroid for mining suitability"""
    try:
        asteroid_id = request.form.get('asteroid_id', '').strip()
        
        if not asteroid_id:
            return jsonify({'success': False, 'error': 'Please enter an asteroid ID or name'})
        
        logger.info(f'Analyzing asteroid: {asteroid_id}')
        rotation_info = get_rotation_period(asteroid_id)
        url = f'{NASA_BASE_URL}{asteroid_id}'
        params = {'api_key': NASA_API_KEY}
        logger.info(f'Calling NASA API: {url}')
        response = requests.get(url, params=params, timeout=10)
        logger.info(f'NASA API response status: {response.status_code}')
        
        if response.status_code != 200:
            logger.warning(f'NASA API error {response.status_code}: {response.text}')
            return create_demo_analysis(asteroid_id, rotation_info)
        
        data = response.json()
        
        asteroid_info = {
            'id': data.get('id', asteroid_id),
            'name': data.get('name', f'Asteroid {asteroid_id}'),
            'nasa_jpl_url': data.get('nasa_jpl_url', '#'),
            'absolute_magnitude': data.get('absolute_magnitude_h', 'Unknown'),
            'is_hazardous': data.get('is_potentially_hazardous_asteroid', False),
            'estimated_diameter': data.get('estimated_diameter', {}),
            'close_approach_data': data.get('close_approach_data', [{}])[0] if data.get('close_approach_data') else {},
            'orbital_data': data.get('orbital_data', {})
        }
        
        logger.info(f'Asteroid info extracted: {asteroid_info["name"]}')
        asteroid_type = determine_asteroid_type(asteroid_info)
        type_info = ASTEROID_TYPES.get(asteroid_type, ASTEROID_TYPES['C-type'])
        scores = calculate_suitability_score(asteroid_info, rotation_info)
        category = get_suitability_category(scores['total'])
        estimated_value = estimate_asteroid_value(type_info['minerals'], asteroid_info)
        
        analysis = {
            'asteroid_type': asteroid_type,
            'type_description': type_info['description'],
            'type_color': type_info['color'],
            'mineral_composition': type_info['minerals'],
            'suitability_score': scores['total'],
            'suitability_category': category,
            'component_scores': scores['components'],
            'estimated_value_billion': round(estimated_value, 2),
            'mining_difficulty': get_mining_difficulty(scores['total']),
            'recommended_approach': get_mining_approach(asteroid_type, scores['components']['size']),
            'rotation_period_hours': rotation_info.get('period_hours'),
            'rotation_data_source': scores.get('rotation_data_source', 'simulated')
        }
        
        logger.info(f'Analysis complete for {asteroid_info["name"]}: score={scores["total"]}')
        
        return jsonify({
            'success': True,
            'asteroid': asteroid_info,
            'analysis': analysis
        })
        
    except requests.exceptions.Timeout:
        logger.error(f'NASA API timeout for {asteroid_id}')
        return jsonify({'success': False, 'error': 'NASA API timeout. Using demo data instead.'})
    except requests.exceptions.RequestException as e:
        logger.error(f'Request error: {str(e)}')
        return jsonify({'success': False, 'error': f'Network error: {str(e)}'})
    except Exception as e:
        logger.error(f'Error analyzing asteroid: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'error': f'Error analyzing asteroid: {str(e)}'})


def create_demo_analysis(asteroid_id, rotation_info=None):
    """Create a demo analysis when NASA API fails"""
    asteroid_type = random.choices(
        ['C-type', 'S-type', 'M-type'],
        weights=[0.75, 0.17, 0.08]
    )[0]
    
    type_info = ASTEROID_TYPES[asteroid_type]
    
    asteroid_info = {
        'id': asteroid_id,
        'name': f'Demo Asteroid {asteroid_id}',
        'nasa_jpl_url': 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html',
        'absolute_magnitude': round(random.uniform(15, 22), 2),
        'is_hazardous': random.choice([True, False]),
        'estimated_diameter': {
            'kilometers': {
                'estimated_diameter_min': round(random.uniform(0.1, 5.0), 2),
                'estimated_diameter_max': round(random.uniform(0.5, 10.0), 2)
            }
        }
    }
    
    scores = calculate_suitability_score(asteroid_info, rotation_info)
    scores['total'] = round(scores['total'], 2)

    category = get_suitability_category(scores['total'])
    estimated_value = estimate_asteroid_value(type_info['minerals'], asteroid_info)
    
    analysis = {
        'asteroid_type': asteroid_type,
        'type_description': type_info['description'],
        'type_color': type_info['color'],
        'mineral_composition': type_info['minerals'],
        'suitability_score': scores['total'],
        'suitability_category': category,
        'component_scores': {k: round(v, 2) for k, v in scores['components'].items()},
        'estimated_value_billion': round(estimated_value, 2),
        'mining_difficulty': get_mining_difficulty(scores['total']),
        'recommended_approach': get_mining_approach(asteroid_type, scores['components']['size']),
        'rotation_period_hours': rotation_info.get('period_hours') if rotation_info else None,
        'rotation_data_source': scores.get('rotation_data_source', 'simulated')
    }
    
    return jsonify({
        'success': True,
        'asteroid': asteroid_info,
        'analysis': analysis,
        'demo': True
    })


def estimate_asteroid_value(minerals, asteroid_data):
    """Estimate asteroid value in billions USD"""
    try:
        mineral_prices = {
            'Nickel-Iron': 2.5,
            'Platinum Group': 30000,
            'Gold': 60000,
            'Water Ice': 0.5,
            'Rare Earth Elements': 100,
            'Cobalt': 33,
            'Copper': 9,
            'Silicon': 2,
            'Carbon Compounds': 1,
            'Magnesium Silicates': 0.5,
            'Iridium': 160000,
            'Palladium': 60000,
            'Silicate Minerals': 0.3
        }
        
        diameter_data = asteroid_data.get('estimated_diameter', {}).get('kilometers', {})
        if diameter_data:
            avg_diameter = (
                diameter_data.get('estimated_diameter_min', 0.5) + 
                diameter_data.get('estimated_diameter_max', 0.5)
            ) / 2
            volume_m3 = (4/3) * 3.14159 * ((avg_diameter * 500) ** 3)
            mass_kg = volume_m3 * 2000
        else:
            mass_kg = 1e12
        
        total_value = 0
        for mineral, fraction in minerals.items():
            if mineral in mineral_prices:
                mineral_mass = mass_kg * fraction
                total_value += mineral_mass * mineral_prices[mineral]
        
        return total_value / 1e9
        
    except:
        return random.uniform(1, 100)


def get_mining_difficulty(score):
    if score >= 75:
        return 'Low'
    elif score >= 50:
        return 'Moderate'
    elif score >= 30:
        return 'High'
    else:
        return 'Very High'


def get_mining_approach(asteroid_type, size_score):
    approaches = {
        'M-type': [
            'Surface mining with magnetic separation',
            'Robotic drilling and extraction',
            'Capture and process in lunar orbit'
        ],
        'S-type': [
            'Drill-based extraction with on-site processing',
            'Selective surface mining',
            'Crushing and separation techniques'
        ],
        'C-type': [
            'Water extraction and in-situ resource utilization',
            'Heating for volatile extraction',
            'Chemical processing for carbon compounds'
        ]
    }
    approach_list = approaches.get(asteroid_type, approaches['C-type'])
    return random.choice(approach_list)


@app.route('/discover')
def discover_asteroids():
    """Discover potentially mineable asteroids"""
    try:
        logger.info('Discovering asteroids')
        
        asteroids = []
        asteroid_names = [
            "Ceres", "Vesta", "Pallas", "Hygiea", "Interamnia",
            "Davida", "Cybele", "Europa", "Sylvia", "Hektor",
            "Juno", "Eunomia", "Psyche", "Thisbe", "Amphitrite"
        ]
        
        for i in range(10):
            asteroid_type = random.choices(
                ['C-type', 'S-type', 'M-type'],
                weights=[0.75, 0.17, 0.08]
            )[0]
            
            type_info = ASTEROID_TYPES[asteroid_type]
            score = random.uniform(40, 90)
            category = get_suitability_category(score)
            
            asteroids.append({
                'id': f'2000{i}',
                'name': f'({2000 + i}) {random.choice(asteroid_names)}',
                'type': asteroid_type,
                'type_color': type_info['color'],
                'suitability_score': round(score, 2),
                'category': category,
                'diameter_km': round(random.uniform(0.5, 5.0), 2),
                'top_minerals': list(type_info['minerals'].keys())[:2]
            })
        
        asteroids.sort(key=lambda x: x['suitability_score'], reverse=True)
        logger.info(f'Generated {len(asteroids)} asteroids')
        
        return jsonify({'success': True, 'asteroids': asteroids})
        
    except Exception as e:
        logger.error(f'Error discovering asteroids: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'error': f'Error discovering asteroids: {str(e)}'})


#if __name__ == '__main__':
    #app.run(debug=True, port=5000)



