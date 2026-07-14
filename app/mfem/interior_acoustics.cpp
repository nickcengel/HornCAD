// Native reference for the reduced HornCAD interior/aperture formulation.
#include <mfem.hpp>

#include <algorithm>
#include <cmath>
#include <complex>
#include <iostream>
#include <map>
#include <string>
#include <vector>

using namespace mfem;

namespace
{
constexpr double pi = 3.14159265358979323846;

struct BoundaryTrace
{
   std::vector<int> dofs;
   std::vector<Vector> points;
   std::vector<double> weights;
};

int vertex_dof(FiniteElementSpace &fes, int vertex)
{
   Array<int> dofs;
   fes.GetVertexDofs(vertex, dofs);
   MFEM_VERIFY(dofs.Size() == 1, "P1 H1 vertex must have one scalar DOF");
   return dofs[0] < 0 ? -1 - dofs[0] : dofs[0];
}

double triangle_area(const double *a, const double *b, const double *c)
{
   const double ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
   const double vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
   const double cx = uy * vz - uz * vy;
   const double cy = uz * vx - ux * vz;
   const double cz = ux * vy - uy * vx;
   return 0.5 * std::sqrt(cx * cx + cy * cy + cz * cz);
}

BoundaryTrace boundary_trace(Mesh &mesh, FiniteElementSpace &fes, int attribute)
{
   std::map<int, double> weights_by_dof;
   std::map<int, Vector> points_by_dof;
   Array<int> vertices;
   for (int element = 0; element < mesh.GetNBE(); ++element)
   {
      if (mesh.GetBdrAttribute(element) != attribute) { continue; }
      mesh.GetBdrElementVertices(element, vertices);
      MFEM_VERIFY(vertices.Size() == 3, "aperture boundaries must be triangular");
      const double *a = mesh.GetVertex(vertices[0]);
      const double *b = mesh.GetVertex(vertices[1]);
      const double *c = mesh.GetVertex(vertices[2]);
      const double share = triangle_area(a, b, c) / 3.0;
      for (int local = 0; local < 3; ++local)
      {
         const int dof = vertex_dof(fes, vertices[local]);
         weights_by_dof[dof] += share;
         Vector point(3);
         const double *coordinates = mesh.GetVertex(vertices[local]);
         for (int axis = 0; axis < 3; ++axis) { point[axis] = coordinates[axis]; }
         points_by_dof[dof] = point;
      }
   }
   BoundaryTrace trace;
   for (const auto &[dof, weight] : weights_by_dof)
   {
      trace.dofs.push_back(dof);
      trace.points.push_back(points_by_dof[dof]);
      trace.weights.push_back(weight);
   }
   MFEM_VERIFY(!trace.dofs.empty(), "requested boundary attribute is empty");
   return trace;
}

void copy_sparse(const SparseMatrix &source, SparseMatrix &real, SparseMatrix &imag)
{
   Array<int> columns;
   Vector values;
   for (int row = 0; row < source.Height(); ++row)
   {
      source.GetRow(row, columns, values);
      for (int entry = 0; entry < columns.Size(); ++entry)
      {
         real.Add(row, columns[entry], values[entry]);
         imag.Add(row, columns[entry], 0.0);
      }
   }
}
} // namespace

int main(int argc, char *argv[])
{
   Mpi::Init(argc, argv);
   if (argc < 3)
   {
      std::cerr << "usage: horncad_mfem_interior MESH.msh FREQUENCY_HZ\n";
      return 2;
   }
   const std::string mesh_path = argv[1];
   const double frequency = std::stod(argv[2]);
   MFEM_VERIFY(frequency > 0.0, "frequency must be positive");
   constexpr double density = 1.2041;
   constexpr double sound_speed = 343.21;
   constexpr double volume_velocity = 1.0;
   const double omega = 2.0 * pi * frequency;
   const double wave_number = omega / sound_speed;

   Mesh mesh(mesh_path.c_str(), 1, 1);
   H1_FECollection collection(1, mesh.Dimension());
   FiniteElementSpace space(&mesh, &collection);
   ConstantCoefficient negative_k_squared(-wave_number * wave_number);
   BilinearForm helmholtz(&space);
   helmholtz.AddDomainIntegrator(new DiffusionIntegrator);
   helmholtz.AddDomainIntegrator(new MassIntegrator(negative_k_squared));
   helmholtz.Assemble();
   helmholtz.Finalize();

   const BoundaryTrace throat = boundary_trace(mesh, space, 2);
   const BoundaryTrace mouth = boundary_trace(mesh, space, 3);
   const int pressure_size = space.GetVSize();
   const int mouth_size = static_cast<int>(mouth.dofs.size());
   const int system_size = pressure_size + mouth_size;
   auto *real = new SparseMatrix(system_size);
   auto *imag = new SparseMatrix(system_size);
   copy_sparse(helmholtz.SpMat(), *real, *imag);

   for (int local = 0; local < mouth_size; ++local)
   {
      imag->Add(mouth.dofs[local], pressure_size + local,
                omega * density * mouth.weights[local]);
      real->Add(mouth.dofs[local], pressure_size + local, 0.0);
      real->Add(pressure_size + local, mouth.dofs[local], -1.0);
      imag->Add(pressure_size + local, mouth.dofs[local], 0.0);
   }
   for (int row = 0; row < mouth_size; ++row)
   {
      for (int column = 0; column < mouth_size; ++column)
      {
         std::complex<double> integral;
         if (row == column)
         {
            const double radius = std::sqrt(mouth.weights[column] / pi);
            integral = 2.0 * pi *
                       (1.0 - std::exp(std::complex<double>(0.0, -wave_number * radius))) /
                       std::complex<double>(0.0, wave_number);
         }
         else
         {
            double distance_squared = 0.0;
            for (int axis = 0; axis < 3; ++axis)
            {
               const double delta = mouth.points[row][axis] - mouth.points[column][axis];
               distance_squared += delta * delta;
            }
            const double distance = std::sqrt(distance_squared);
            integral = mouth.weights[column] *
                       std::exp(std::complex<double>(0.0, -wave_number * distance)) /
                       distance;
         }
         const std::complex<double> impedance =
            std::complex<double>(0.0, density * omega / (2.0 * pi)) * integral;
         real->Add(pressure_size + row, pressure_size + column, impedance.real());
         imag->Add(pressure_size + row, pressure_size + column, impedance.imag());
      }
   }
   real->Finalize(0);
   imag->Finalize(0);
   ComplexSparseMatrix system(real, imag, true, true);

   Vector rhs(2 * system_size), solution(2 * system_size);
   rhs = 0.0;
   solution = 0.0;
   double throat_area = 0.0;
   for (double weight : throat.weights) { throat_area += weight; }
   const double derivative_imaginary = omega * density * volume_velocity / throat_area;
   for (int local = 0; local < static_cast<int>(throat.dofs.size()); ++local)
   {
      rhs[system_size + throat.dofs[local]] +=
         derivative_imaginary * throat.weights[local];
   }
   ComplexUMFPackSolver solver(system);
   solver.SetPrintLevel(0);
   solver.Mult(rhs, solution);

   Vector residual(2 * system_size);
   system.Mult(solution, residual);
   residual -= rhs;
   double mouth_area = 0.0, radiated_power = 0.0;
   for (int local = 0; local < mouth_size; ++local)
   {
      const int pressure_dof = mouth.dofs[local];
      const int velocity_dof = pressure_size + local;
      const std::complex<double> pressure(solution[pressure_dof],
                                          solution[system_size + pressure_dof]);
      const std::complex<double> velocity(solution[velocity_dof],
                                          solution[system_size + velocity_dof]);
      mouth_area += mouth.weights[local];
      radiated_power += 0.5 * mouth.weights[local] *
                        std::real(pressure * std::conj(velocity));
   }
   std::cout << "frequency_hz=" << frequency
             << " pressure_dofs=" << pressure_size
             << " mouth_dofs=" << mouth_size
             << " throat_area_m2=" << throat_area
             << " mouth_area_m2=" << mouth_area
             << " radiated_power_w=" << radiated_power
             << " relative_residual=" << residual.Norml2() / rhs.Norml2()
             << std::endl;
   return 0;
}
