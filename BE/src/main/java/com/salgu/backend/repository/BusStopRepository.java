package com.salgu.backend.repository;

import com.salgu.backend.domain.BusStop;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BusStopRepository extends JpaRepository<BusStop, Long> {
}
