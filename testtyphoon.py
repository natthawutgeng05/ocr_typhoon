from openai import OpenAI

# Initialize the client with your API key and the OpenTyphoon base URL
client = OpenAI(
    api_key="apikey",
    base_url="https://api.opentyphoon.ai/v1"
)

# Make a completion request
response = client.chat.completions.create(
    model="typhoon-v2.1-12b-instruct",
    messages=[
        {"role": "system", "content": "You are a helpful assistant. You must answer only in Thai."},
        {"role": "user", "content": "ขอสูตรไก่ย่าง"}
    ],
    max_tokens=512,
    temperature=0.6
)

# Print the response
print(response.choices[0].message.content)
