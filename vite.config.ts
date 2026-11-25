import { defineConfig } from 'vite';
export default defineConfig({
  server: {
    host: '127.0.0.1',
    fs: {
      strict: true,
      deny: ['.env', '.env.*', '**/.git/**', '**/data/**', '**/reference/**', '**/backups/**',
        '**/*.{pem,crt,key,pfx,db,sqlite,xlsx,xlsm,dpapi,strengthbackup}'],
    },
    proxy: {'/api': 'http://127.0.0.1:8000'},
  },
});
