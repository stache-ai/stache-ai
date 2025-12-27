FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci

# Copy source code
COPY . .

# Build for production
RUN npm run build

# Production stage
FROM node:20-alpine

WORKDIR /app

# Install serve for static file serving
RUN npm install -g serve

# Copy built files from builder
COPY --from=builder /app/dist ./dist

# Expose port
EXPOSE 3000

# Serve the built static files
CMD ["serve", "-s", "dist", "-l", "3000"]
