package com.salgu.backend.repository;

import com.salgu.backend.domain.HousingPolicy;
import org.springframework.data.jpa.repository.JpaRepository;

public interface HousingPolicyRepository extends JpaRepository<HousingPolicy, Long> {
}
