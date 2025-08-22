FROM node:20-alpine

WORKDIR /app

# Copy full package.json and lockfile if present
COPY package.json package-lock.json* ./

# Force install all deps (Next, React, Tailwind)
RUN npm install --legacy-peer-deps

# Copy rest of the app
COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]