import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcrypt';
import 'dotenv/config';

const prisma = new PrismaClient();

async function main() {
  console.log('🌱 Seeding auth infrastructure...\n');

  const adminRole = await prisma.role.upsert({
    where: { name: 'admin' },
    update: {},
    create: {
      name: 'admin',
      description: 'Full system administrator',
      permissions: ['*'],
    },
  });

  const userRole = await prisma.role.upsert({
    where: { name: 'user' },
    update: {},
    create: {
      name: 'user',
      description: 'Standard user',
      permissions: ['read', 'write'],
    },
  });

  const password = process.env.SEED_ADMIN_PASSWORD || 'changeme';
  const hashedPassword = await bcrypt.hash(password, 10);

  const admin = await prisma.user.upsert({
    where: { email: 'admin@artifact.virtual' },
    update: { password: hashedPassword },
    create: {
      email: 'admin@artifact.virtual',
      password: hashedPassword,
      firstName: 'Ali',
      lastName: 'Shakil',
      roleId: adminRole.id,
    },
  });

  console.log('✅ Admin role:', adminRole.id);
  console.log('✅ User role:', userRole.id);
  console.log('✅ Admin user:', admin.email);
}

main()
  .catch((e) => { console.error(e); process.exit(1); })
  .finally(() => prisma.$disconnect());
