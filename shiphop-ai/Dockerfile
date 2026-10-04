# ShipHop.AI — single-container deploy.
FROM node:20-alpine
WORKDIR /app
COPY server/package*.json ./server/
RUN cd server && npm install --omit=dev
COPY server ./server
COPY public ./public
ENV NODE_ENV=production
EXPOSE 8787
WORKDIR /app/server
CMD ["node", "src/app.js"]
