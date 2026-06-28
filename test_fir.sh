#!/bin/bash
echo "=== SETUP ==="
curl -s -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fir-test-session-001",
    "message": "I had an accident on NH44 near Panipat toll plaza. My motorcycle collided with a truck. I have a leg injury and there were 2 witnesses. The truck number was HR55X9012.",
    "location": {"lat": 29.39, "lng": 76.96},
    "lang": "en"
  }'

curl -s -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fir-test-session-001",
    "message": "The accident happened around 9 AM this morning. My bike number is HR26AB1234. I am conscious but in pain.",
    "location": {"lat": 29.39, "lng": 76.96},
    "lang": "en"
  }'

echo -e "\n\n=== TEST 1: Generate FIR ==="
RESP1=$(curl -s -X POST http://localhost:8000/api/v1/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fir-test-session-001",
    "additional_info": {
      "vehicle_numbers": ["HR26AB1234", "HR55X9012"],
      "witnesses": 2,
      "injuries_count": 1,
      "accident_time": "2026-06-28T09:00:00+05:30",
      "accident_type": "two_wheeler_collision",
      "reporting_person_name": "Mayank Maheshwari",
      "reporting_person_phone": "9876543210"
    },
    "lang": "en"
  }')
echo $RESP1 | python3 -m json.tool
REPORT_ID=$(echo $RESP1 | python3 -c "import sys, json; print(json.load(sys.stdin).get('report_id', ''))")

echo -e "\n\n=== TEST 2: Verify plain text ==="
echo $RESP1 | python3 -c "import sys, json; print(json.load(sys.stdin).get('download_text', ''))"

echo -e "\n\n=== TEST 3: Retrieve stored report ==="
curl -s http://localhost:8000/api/v1/report/$REPORT_ID | python3 -m json.tool

echo -e "\n\n=== TEST 4: Hindi FIR generation ==="
curl -s -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fir-test-session-hindi",
    "message": "मेरी गाड़ी NH44 पर एक ट्रक से टकरा गई। मेरे पैर में चोट है।",
    "location": {"lat": 29.39, "lng": 76.96},
    "lang": "hi"
  }' > /dev/null

curl -s -X POST http://localhost:8000/api/v1/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fir-test-session-hindi",
    "additional_info": {
      "vehicle_numbers": ["HR26AB1234"],
      "injuries_count": 1,
      "accident_type": "two_wheeler_collision"
    },
    "lang": "hi"
  }' | python3 -m json.tool

echo -e "\n\n=== TEST 5: Session not found ==="
curl -s -X POST http://localhost:8000/api/v1/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "nonexistent-session-xyz",
    "additional_info": {},
    "lang": "en"
  }' | python3 -m json.tool

echo -e "\n\n=== TEST 6: Report not found ==="
curl -s http://localhost:8000/api/v1/report/00000000-0000-0000-0000-000000000000 | python3 -m json.tool

echo -e "\n\n=== TEST 7: Decode WhatsApp URL ==="
echo $RESP1 | python3 -c "
import sys, json
from urllib.parse import unquote
url = json.load(sys.stdin).get('share_whatsapp_url', '')
if '?text=' in url:
    text = url.split('?text=')[1]
    print(unquote(text))
"

echo -e "\n\n=== TEST 8: Minimal info ==="
curl -s -X POST http://localhost:8000/api/v1/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fir-test-session-001",
    "additional_info": {},
    "lang": "en"
  }' | python3 -m json.tool
