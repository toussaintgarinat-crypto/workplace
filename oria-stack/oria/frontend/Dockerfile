FROM node:20-alpine
# Build context = workspace root — needed for shared-ui (file:../../shared-ui)
WORKDIR /workspace
COPY shared-ui ./shared-ui
WORKDIR /workspace/oria/frontend
COPY oria/frontend/package.json ./
RUN npm install
COPY oria/frontend/ ./
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host"]
